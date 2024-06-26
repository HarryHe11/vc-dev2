import torch
import torch.nn as nn
from models.tts.vc.ns2_uniamphion import UniAmphionVC
from safetensors.torch import load_model
from transformers import AutoProcessor, AutoModel
import torch
import torch.nn as nn
import torch.nn.functional as F


# -*- coding: utf-8 -*- #
"""*********************************************************************************************"""
#   FileName     [ model.py ]
#   Synopsis     [ the linear model ]
#   Author       [ S3PRL ]
#   Copyright    [ Copyleft(c), Speech Lab, NTU, Taiwan ]
"""*********************************************************************************************"""

class SAP(nn.Module):
    ''' Self Attention Pooling module incoporate attention mask'''

    def __init__(self, out_dim, input_dim):
        super(SAP, self).__init__()

        # Setup
        self.act_fn = nn.ReLU()
        self.linear = nn.Linear(input_dim, out_dim)
        self.sap_layer = SelfAttentionPooling(out_dim)
    
    def forward(self, feature, att_mask):

        ''' 
        Arguments
            feature - [BxTxD]   Acoustic feature with shape 
            att_mask   - [BxTx1]     Attention Mask logits
        '''
        #Encode
        feature = self.act_fn(feature)
        feature = self.linear(feature)
        sap_vec = self.sap_layer(feature, att_mask)

        return sap_vec

class SelfAttentionPooling(nn.Module):
    """
    Implementation of SelfAttentionPooling 
    Original Paper: Self-Attention Encoding and Pooling for Speaker Recognition
    https://arxiv.org/pdf/2008.01077v1.pdf
    """
    def __init__(self, input_dim):
        super(SelfAttentionPooling, self).__init__()
        self.W = nn.Linear(input_dim, 1)
    def forward(self, batch_rep, att_mask):
        """
        input:
        batch_rep : size (N, T, H), N: batch size, T: sequence length, H: Hidden dimension
        
        attention_weight:
        att_w : size (N, T, 1)
        
        return:
        utter_rep: size (N, H)
        """
        seq_len = batch_rep.shape[1]
        softmax = nn.functional.softmax
        att_logits = self.W(batch_rep).squeeze(-1)
        att_logits = att_mask + att_logits
        att_w = softmax(att_logits, dim=-1).unsqueeze(-1)
        utter_rep = torch.sum(batch_rep * att_w, dim=1)

        return utter_rep



class AdMSoftmaxLoss(nn.Module):

    def __init__(self, in_features, out_features, s=30.0, m=0.4):
        '''
        AM Softmax Loss
        '''
        super(AdMSoftmaxLoss, self).__init__()
        self.s = s
        self.m = m
        self.in_features = in_features
        self.out_features = out_features
        self.fc = nn.Linear(in_features, out_features, bias=False)

    def forward(self, x, labels):
        '''
        input shape (N, in_features)
        '''
        assert len(x) == len(labels), print(x.shape, labels.shape)
        assert torch.min(labels) >= 0
        assert torch.max(labels) < self.out_features
        labels = labels.reshape(-1)
        # print([x].shape)
        for W in self.fc.parameters():
            W = F.normalize(W, dim=1)

        x = F.normalize(x, dim=1)

        wf = self.fc(x)
        numerator = self.s * (torch.diagonal(wf.transpose(0, 1)[labels]) - self.m)
        excl = torch.cat([torch.cat((wf[i, :y], wf[i, y+1:])).unsqueeze(0) for i, y in enumerate(labels)], dim=0)
        denominator = torch.exp(numerator) + torch.sum(torch.exp(self.s * excl), dim=1)
        L = numerator - torch.log(denominator)
        return -torch.mean(L)
    
class TDNN(nn.Module):
    def __init__(
                    self, 
                    input_dim=23, 
                    output_dim=512,
                    context_size=5,
                    stride=1,
                    dilation=1,
                    batch_norm=True,
                    dropout_p=0.0
                ):
        super(TDNN, self).__init__()
        self.context_size = context_size
        self.stride = stride
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.dilation = dilation
        self.dropout_p = dropout_p
        self.batch_norm = batch_norm
      
        self.kernel = nn.Linear(input_dim*context_size, output_dim)
        self.nonlinearity = nn.ReLU()
        if self.batch_norm:
            self.bn = nn.BatchNorm1d(output_dim)
        if self.dropout_p:
            self.drop = nn.Dropout(p=self.dropout_p)
        
    def forward(self, x):
        '''
        input: size (batch, seq_len, input_features)
        outpu: size (batch, new_seq_len, output_features)
        '''
        _, _, d = x.shape
        assert (d == self.input_dim), 'Input dimension was wrong. Expected ({}), got ({})'.format(self.input_dim, d)
        x = x.unsqueeze(1)
        # Unfold input into smaller temporal contexts
        x = F.unfold(
                        x, 
                        (self.context_size, self.input_dim), 
                        stride=(1,self.input_dim), 
                        dilation=(self.dilation,1)
                    )
        # N, output_dim*context_size, new_t = x.shape
        x = x.transpose(1,2)
        x = self.kernel(x)
        x = self.nonlinearity(x)
        if self.dropout_p:
            x = self.drop(x)
        if self.batch_norm:
            x = x.transpose(1,2)
            x = self.bn(x)
            x = x.transpose(1,2)
        return x

class XVector(nn.Module):
    def __init__(self, input_dim=512, output_dim = 1500, nOut=512):
        super(XVector, self).__init__()
        # simply take mean operator / no additional parameters
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.nOut = nOut
        self.module = nn.Sequential(
            TDNN(input_dim=self.input_dim, output_dim=self.input_dim, context_size=5, dilation=1),
            TDNN(input_dim=self.input_dim, output_dim=self.input_dim, context_size=3, dilation=2),
            TDNN(input_dim=self.input_dim, output_dim=self.input_dim, context_size=3, dilation=3),
            TDNN(input_dim=self.input_dim, output_dim=self.input_dim, context_size=1, dilation=1),
            TDNN(input_dim=self.input_dim, output_dim=self.output_dim, context_size=1, dilation=1),
        )
        p_dropout = 0.1
        self.fc1 = nn.Linear(2 * self.output_dim, self.input_dim)
        self.bn_fc1 = nn.BatchNorm1d(self.input_dim, momentum=0.1, affine=False)
        self.dropout_fc1 = nn.Dropout(p=p_dropout)

        self.fc2 = nn.Linear(self.input_dim, self.input_dim)
        self.bn_fc2 = nn.BatchNorm1d(self.input_dim, momentum=0.1, affine=False)
        self.dropout_fc2 = nn.Dropout(p=p_dropout)

        self.fc3 = nn.Linear(self.input_dim, self.nOut)

    def forward(self, feature):
        x = self.module(feature)
        # B x T X D --> B x D x T
        x = x. transpose(1, 2)   
        stats = torch.cat((x.mean(dim=2), x.std(dim=2)), dim=1)
        x = self.dropout_fc1(self.bn_fc1(F.relu(self.fc1(stats))))
        x = self.dropout_fc2(self.bn_fc2(F.relu(self.fc2(x))))
        x = self.fc3(x)
        return x



class SVMODEL(nn.Module):
    def __init__(self, config, num_speakers, vc_model_path):
        super().__init__() 
        self.vc_model = UniAmphionVC(config)
        print(f"Loading VC model from {vc_model_path}")
        load_model(self.vc_model, vc_model_path)
        self.num_speakers = num_speakers
        self.speaker_encoder = self.vc_model.reference_encoder
        self.speaker_encoder.eval()
        # freeze the speaker encoder
        for param in self.speaker_encoder.parameters():
            param.requires_grad = False
        self.x_vector = XVector(input_dim = self.speaker_encoder.encoder_hidden, output_dim=1500, nOut=512)
        self.amsoftmax = AdMSoftmaxLoss(self.x_vector.nOut, out_features=num_speakers) 
        

    def forward(self, x, x_mask, x_speaker):
        with torch.no_grad():
            _, encoded_x = self.speaker_encoder(x_ref=x, key_padding_mask=x_mask)
            
        spk_emb = self.x_vector(encoded_x)
        am_loss = self.amsoftmax(spk_emb, x_speaker)
        return am_loss
    

class SVMODEL_SSL(nn.Module):
    def __init__(self, num_speakers):
        super().__init__()
        self.num_speakers = num_speakers
        self.speaker_encoder = AutoModel.from_pretrained("/mnt/data3/hehaorui/ckpt/wav2vec/wav2vec-base/")
        self.speaker_encoder.eval()
        # freeze the speaker encoder
        for param in self.speaker_encoder.parameters():
            param.requires_grad = False
      
        # Assuming 768 as the output dimension for wav2vec 2.0 base model
        # self.x_vector = XVector(input_dim=768, output_dim=1500, nOut=512)

        self.fc = nn.Linear(768, 512)
        self.relu = nn.ReLU()

        self.amsoftmax = AdMSoftmaxLoss(in_features=512, out_features=num_speakers)
        

    def forward(self, x, x_mask, x_speaker):
        with torch.no_grad():
            outputs = self.speaker_encoder(x, attention_mask=x_mask)
            encoded_x = outputs.last_hidden_state #  B x T x D
            
        # spk_emb = self.x_vector(encoded_x)
        # mean
        spk_emb = torch.mean(encoded_x, dim=1)
        spk_emb = self.fc(spk_emb)
        spk_emb = self.relu(spk_emb)
        am_loss = self.amsoftmax(spk_emb, x_speaker)
        return am_loss

if __name__ == "__main__":
    model = SVMODEL_SSL(num_speakers=10)
    x = torch.randn(2, 16000)  # example shape for raw waveform input
    x_mask = torch.ones(2, 16000).to(torch.bool)  # wav2vec 2.0 uses boolean masks
    x_speaker = torch.randint(0, 10, (2,))
    loss = model(x, x_mask, x_speaker)
    print(loss)
