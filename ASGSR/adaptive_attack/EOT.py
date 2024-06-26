import torch.nn as nn
import torch

# EOT forward() returns: 
# `scores`: This variable contains the predicted scores or logits for each class, 
# averaged over all the different transformations of the input data that were generated during the EOT process. 
# The shape of the scores tensor is (batch_size, n_classes), where batch_size is the number of input examples 
# and n_classes is the number of classes in the classification task. The scores can be interpreted as the 
# probabilities or confidences assigned by the model to each class.

# `loss`: This variable contains the average loss computed over all the different transformations of the 
# input data. The loss is a scalar value that measures the discrepancy between the predicted scores 
# and the true labels for each input example. The specific loss function used in the code is passed as 
# a parameter when creating an instance of the EOT class.

# `grad`: This variable contains the gradients of the loss with respect to the input data, averaged over 
# all the different transformations of the input data. The grad tensor has the same shape as the input 
# data tensor, (batch_size, n_channels, max_len). The gradients can be used to update the input data in 
# order to improve the model's performance or to perform adversarial attacks.

# `decisions`: This variable is a list of lists containing the predicted class labels for each input example,
#  for each of the different transformations of the input data generated during the EOT process. The length 
# of the outer list is equal to the number of input examples, and the length of the inner list is equal 
# to the number of transformations. The decisions variable can be useful for analyzing the variability of 
# the model's predictions across different input conditions, or for ensemble methods that combine multiple 
# predictions to improve accuracy.

# EOT forward() returns:
# `scores`: This variable contains the predicted scores or logits for each class,
# averaged over all the different transformations of the input data that were generated during the EOT process.
# The shape of the scores tensor is (batch_size, n_classes), where batch_size is the number of input examples
# and n_classes is the number of classes in the classification task. The scores can be interpreted as the
# probabilities or confidences assigned by the model to each class.

# `loss`: This variable contains the average loss computed over all the different transformations of the
# input data. The loss is a scalar value that measures the discrepancy between the predicted scores
# and the true labels for each input example. The specific loss function used in the code is passed as
# a parameter when creating an instance of the EOT class.

# `grad`: This variable contains the gradients of the loss with respect to the input data, averaged over
# all the different transformations of the input data. The grad tensor has the same shape as the input
# data tensor, (batch_size, n_channels, max_len). The gradients can be used to update the input data in
# order to improve the model's performance or to perform adversarial attacks.

# `decisions`: This variable is a list of lists containing the predicted class labels for each input example,
#  for each of the different transformations of the input data generated during the EOT process. The length
# of the outer list is equal to the number of input examples, and the length of the inner list is equal
# to the number of transformations. The decisions variable can be useful for analyzing the variability of
# the model's predictions across different input conditions, or for ensemble methods that combine multiple
# predictions to improve accuracy.

class EOT(nn.Module):

    def __init__(self, model, loss, EOT_size=1, EOT_batch_size=1, use_grad=True):
        super().__init__()
        self.model = model
        self.loss = loss
        self.EOT_size = EOT_size
        self.EOT_batch_size = EOT_batch_size
        self.EOT_num_batches = self.EOT_size // self.EOT_batch_size
        self.use_grad = use_grad

    def forward(self, x_batch, y_batch, EOT_num_batches=None, EOT_batch_size=None, use_grad=None):
        EOT_num_batches = EOT_num_batches if EOT_num_batches else self.EOT_num_batches
        EOT_batch_size = EOT_batch_size if EOT_batch_size else self.EOT_batch_size
        use_grad = use_grad if use_grad else self.use_grad
        n_audios, n_channels, max_len = x_batch.size()
        # n_audios, max_len = x_batch.size()

        grad = None
        scores = None
        loss = 0
        # decisions = [[]] * n_audios ## wrong, all element shares the same memory
        decisions = [[] for _ in range(n_audios)]
        for EOT_index in range(EOT_num_batches):
            x_batch_repeat = x_batch.repeat(EOT_batch_size, 1, 1)
            # x_batch_repeat = x_batch.repeat(EOT_batch_size, 1)
            if use_grad:
                x_batch_repeat.retain_grad()
            y_batch_repeat = y_batch.repeat(EOT_batch_size)
            # scores_EOT = self.model(x_batch_repeat) # scores or logits. Just Name it scores. (batch_size, n_spks)
            decisions_EOT, scores_EOT = self.model.make_decision(
                x_batch_repeat)  # scores or logits. Just Name it scores. (batch_size, n_spks)
            loss_EOT = self.loss(scores_EOT, y_batch_repeat)
            if use_grad:
                loss_EOT.backward(torch.ones_like(loss_EOT))

            if EOT_index == 0:
                scores = scores_EOT.view(EOT_batch_size, -1, scores_EOT.shape[1]).mean(0)
                loss = loss_EOT.view(EOT_batch_size, -1).mean(0)
                if use_grad:
                    grad = x_batch_repeat.grad.view(EOT_batch_size, -1, n_channels, max_len).mean(0)
                    # grad = x_batch_repeat.grad.view(EOT_batch_size, -1, max_len).mean(0)
                    x_batch_repeat.grad.zero_()
            else:
                scores.data += scores_EOT.view(EOT_batch_size, -1, scores.shape[1]).mean(0)
                loss.data += loss_EOT.view(EOT_batch_size, -1).mean(0)
                if use_grad:
                    grad.data += x_batch_repeat.grad.view(EOT_batch_size, -1, n_channels, max_len).mean(0)
                    # grad.data += x_batch_repeat.grad.view(EOT_batch_size, -1, max_len).mean(0)
                    x_batch_repeat.grad.zero_()

            decisions_EOT = decisions_EOT.view(EOT_batch_size, -1).detach().cpu().numpy()
            for ii in range(n_audios):
                decisions[ii] += list(decisions_EOT[:, ii])

        return scores, loss, grad, decisions


class EOTSV(nn.Module):

    def __init__(self, model, loss, EOT_size=1, EOT_batch_size=1, use_grad=True):
        super().__init__()
        self.model = model
        self.loss = loss
        self.EOT_size = EOT_size
        self.EOT_batch_size = EOT_batch_size
        self.EOT_num_batches = self.EOT_size // self.EOT_batch_size
        self.use_grad = use_grad

    def forward(self, x1_batch, x2_batch, y_batch, EOT_num_batches=None, EOT_batch_size=None, use_grad=None,
                model=None):
        if model is None:
            model = self.model
        EOT_num_batches = EOT_num_batches if EOT_num_batches else self.EOT_num_batches
        EOT_batch_size = EOT_batch_size if EOT_batch_size else self.EOT_batch_size
        use_grad = use_grad if use_grad else self.use_grad
        n_audios, n_channels, max_len = x2_batch.size()
        # n_audios, max_len = x2_batch.size()
        grad = None
        scores = None
        loss = 0
        # decisions = [[]] * n_audios ## wrong, all element shares the same memory
        decisions = [[] for _ in range(n_audios)]
        for EOT_index in range(EOT_num_batches):
            x1_batch_repeat = x1_batch.repeat(EOT_batch_size, 1, 1)
            x2_batch_repeat = x2_batch.repeat(EOT_batch_size, 1, 1)
            # x1_batch_repeat = x1_batch.repeat(EOT_batch_size, 1)
            # x2_batch_repeat = x2_batch.repeat(EOT_batch_size, 1)
            if use_grad:
                x2_batch_repeat.retain_grad()
            y_batch_repeat = y_batch.repeat(EOT_batch_size)
            # scores_EOT = self.model(x_batch_repeat) # scores or logits. Just Name it scores. (batch_size, n_spks)
            decisions_EOT, scores_EOT = model.make_decision_SV(
                x1_batch_repeat, x2_batch_repeat)  # scores or logits. Just Name it scores. (batch_size, n_spks)
            # decisions_EOT = torch.unsqueeze(decisions_EOT, 1)
            # scores_EOT = torch.unsqueeze(scores_EOT, 1)
            loss_EOT = self.loss(scores_EOT, y_batch_repeat)
            scores_EOT = torch.unsqueeze(scores_EOT, 1)
            if use_grad:
                loss_EOT.backward(torch.ones_like(loss_EOT))

            if EOT_index == 0:
                scores = scores_EOT.view(EOT_batch_size, -1, scores_EOT.shape[1]).mean(0)
                loss = loss_EOT.view(EOT_batch_size, -1).mean(0)
                if use_grad:
                    grad = x2_batch_repeat.grad.view(EOT_batch_size, -1, n_channels, max_len).mean(0)
                    # grad = x2_batch_repeat.grad.view(EOT_batch_size, -1, max_len).mean(0)
                    x2_batch_repeat.grad.zero_()
            else:
                scores.data += scores_EOT.view(EOT_batch_size, -1, scores.shape[1]).mean(0)
                loss.data += loss_EOT.view(EOT_batch_size, -1).mean(0)
                if use_grad:
                    grad.data += x2_batch_repeat.grad.view(EOT_batch_size, -1, n_channels, max_len).mean(0)
                    # grad.data += x2_batch_repeat.grad.view(EOT_batch_size, -1, max_len).mean(0)
                    x2_batch_repeat.grad.zero_()

            decisions_EOT = decisions_EOT.view(EOT_batch_size, -1).detach().cpu().numpy()
            for ii in range(n_audios):
                decisions[ii] += list(decisions_EOT[:, ii])

        return scores, loss, grad, decisions


class EOTSVEnsemble(nn.Module):

    def __init__(self, model, EOT_size=1, EOT_batch_size=1, use_grad=True):
        super().__init__()
        self.model = model
        self.EOT_size = EOT_size
        self.EOT_batch_size = EOT_batch_size
        self.EOT_num_batches = self.EOT_size // self.EOT_batch_size
        self.use_grad = use_grad

    def forward(self, x1_batch, x2_batch, y_batch, EOT_num_batches=None, EOT_batch_size=None, use_grad=None,
                model=None):
        EOT_num_batches = EOT_num_batches if EOT_num_batches else self.EOT_num_batches
        EOT_batch_size = EOT_batch_size if EOT_batch_size else self.EOT_batch_size
        use_grad = use_grad if use_grad else self.use_grad
        n_audios, n_channels, max_len = x2_batch.size()

        grad = None
        scores = None
        loss = 0
        # decisions = [[]] * n_audios ## wrong, all element shares the same memory
        decisions = [[] for _ in range(n_audios)]
        for EOT_index in range(EOT_num_batches):
            # for m in self.model:
            # x_batch_repeat = x_batch.repeat(EOT_batch_size, 1, 1)
            x1_batch_repeat = x1_batch.repeat(EOT_batch_size, 1, 1)
            x2_batch_repeat = x2_batch.repeat(EOT_batch_size, 1, 1)
            if use_grad:
                x2_batch_repeat.retain_grad()
            y_batch_repeat = y_batch.repeat(EOT_batch_size)
            # scores_EOT = self.model(x_batch_repeat) # scores or logits. Just Name it scores. (batch_size, n_spks)
            decisions_EOT, scores_EOT = model.make_decision_SV(
                x1_batch_repeat, x2_batch_repeat)  # scores or logits. Just Name it scores. (batch_size, n_spks)
            # decisions_EOT = torch.unsqueeze(decisions_EOT, 1)
            # loss_EOT = self.loss(scores_EOT, y_batch_repeat)
            loss_EOT = model.threshold - scores_EOT
            scores_EOT = torch.unsqueeze(scores_EOT, 1)

            if use_grad:
                loss_EOT.backward(torch.ones_like(loss_EOT))

            if EOT_index == 0:
                scores = scores_EOT.view(EOT_batch_size, -1, scores_EOT.shape[1]).mean(0)
                loss = loss_EOT.view(EOT_batch_size, -1).mean(0)
                if use_grad:
                    grad = x2_batch_repeat.grad.view(EOT_batch_size, -1, n_channels, max_len).mean(0)
                    # grad = x2_batch_repeat.grad.view(EOT_batch_size, -1, max_len).mean(0)
                    x2_batch_repeat.grad.zero_()
            else:
                scores.data += scores_EOT.view(EOT_batch_size, -1, scores.shape[1]).mean(0)
                loss.data += loss_EOT.view(EOT_batch_size, -1).mean(0)
                if use_grad:
                    grad.data += x2_batch_repeat.grad.view(EOT_batch_size, -1, n_channels, max_len).mean(0)
                    # grad.data += x2_batch_repeat.grad.view(EOT_batch_size, -1, max_len).mean(0)
                    x2_batch_repeat.grad.zero_()

            decisions_EOT = decisions_EOT.view(EOT_batch_size, -1).detach().cpu().numpy()
            for ii in range(n_audios):
                decisions[ii] += list(decisions_EOT[:, ii])

        return scores, loss, grad, decisions
