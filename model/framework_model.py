"""
A general framework for the classification task.
It consists of:
- A Corpus Encoder to create an embedding of the corpus for both ECB and FED.
- A concatenation of that embedding with nontextual data from the data points.
- A classification head, which for now is nothing but a simple MLP with an adjustable amount of layers and neurons.

x_nontext   --- [Non-textual pipeline] ----- \
                                              \
                                                [Concat] ---- [MLP] ---- Sigmoid ----> output 
                                              /
(x_text, x_mask) --[ Corpus Encoder ] -------/

"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from .mlp import MLP, CompactMLP, SimpleMLP, init_weights
from .vector_attention import VectorAttention, CNN1D, ResidualCNN, Residual1DCNN

from .model_01.model import CorpusEncoder as CorpusEncoder01
from .model_02.model import CorpusEncoder as CorpusEncoder02
from .model_03.model import CorpusEncoder as CorpusEncoder03, AttentionWithContext

import numpy as np


nontextual_cols = ['Index - 9',
 'Index - 8',
 'Index - 7',
 'Index - 6',
 'Index - 5',
 'Index - 4',
 'Index - 3',
 'Index - 2',
 'Index - 1',
 'Index - 0',
 'Index Name_CVIX Index',
 'Index Name_EURUSD Curncy',
 'Index Name_EURUSDV1M Curncy',
 'Index Name_MOVE Index',
 'Index Name_SPX Index',
 'Index Name_SRVIX Index',
 'Index Name_SX5E Index',
 'Index Name_V2X Index',
 'Index Name_VIX Index']

index_names = [
 'Index Name_CVIX Index',
 'Index Name_EURUSD Curncy',
 'Index Name_EURUSDV1M Curncy',
 'Index Name_MOVE Index',
 'Index Name_SPX Index',
 'Index Name_SRVIX Index',
 'Index Name_SX5E Index',
 'Index Name_V2X Index',
 'Index Name_VIX Index'
]

index_times = [
 'Index - 9',
 'Index - 8',
 'Index - 7',
 'Index - 6',
 'Index - 5',
 'Index - 4',
 'Index - 3',
 'Index - 2',
 'Index - 1',
 'Index - 0',
]

nontext_dim = len(nontextual_cols)

class ClassificationHead(nn.Module):
    """
    A classification head with an adjustable amount of corpus dimension and nontextual dimension.
    This is just a MLP.
    """
    
    def __init__(self, corpus_emb_dim, nontext_dim, layers=3, mlp_hidden_dim=128, dropout=0, residual=False):
        super(ClassificationHead, self).__init__()
        self.layers = layers
        self.corpus_emb_dim = corpus_emb_dim
        self.nontext_dim = nontext_dim
        # print(nontext_dim, layers, mlp_hidden_dim)
        if residual:
            self.mlp = CompactMLP(nontext_dim, layers, mlp_hidden_dim, out_features=1, dropout=dropout)
        else:
            self.mlp = SimpleMLP(nontext_dim, layers, mlp_hidden_dim, out_features=1, dropout=dropout)
        self.vector_attention = VectorAttention(nontext_dim)
        self.proj = nn.Linear(corpus_emb_dim, nontext_dim, bias=False)
        self.apply(init_weights)

    def forward(self, x_corpus, x_nontext):
        if (x_corpus is None or self.corpus_emb_dim == 0) and (x_nontext is None or self.nontext_dim == 0):
            raise ValueError("Both entries are None.")
        if x_corpus is None or self.corpus_emb_dim == 0:
            x = x_nontext
        elif x_nontext is None or self.nontext_dim == 0:
            x = x_corpus
        else:
            # x = torch.cat([x_corpus, x_nontext], dim=1).float()
            # Vector attention
            x_corpus = self.proj(x_corpus)
            # print(x_corpus.size(), x_nontext.size())
            x = self.vector_attention(sequence=x_nontext, vector=x_corpus)
        out = self.mlp(x)
        return out.view(-1)
    

class NontextualNetwork(nn.Module):
    """
    A network to process nontextual data.
    """
    
    def __init__(self, input_dim, input_channels, output_dim=nontext_dim, layers_nontext=3, dropout=0):
        super(NontextualNetwork, self).__init__()
        self.layers_nontext = layers_nontext
        self.input_dim = input_dim
        self.input_channels = input_channels
        self.output_dim = output_dim
        self.category_embedding = nn.Linear(9, input_channels-1, bias=True)
        self.cnn = CNN1D(input_channels, output_dim, layers_nontext, dropout)
        

    def forward(self, x):
        """Forward method for the NontextualNetwork.
        """
        x_ = x[:, :10]
        category = x[:, 10:]
        # x is of size (batch_size, 10)
        cat_feat = self.category_embedding(category).unsqueeze(-1) # (batch_size, 15, 1)
        cat_feat = cat_feat.repeat(1, 1, x_.size(1))
        x = torch.cat([cat_feat, x_.unsqueeze(1)], dim=1).float()
        # (batch_size, input_channels, 10)
        x = self.cnn(x)
        # x = x.transpose(2, 1)
        #x = x.unsqueeze(-1)
        # x is of shape (batch_size, L=10, H_out=output_dim)
        return x
        




class CorpusEncoder(nn.Module):
    """Generic Corpus encoder for both ECB and FED texts.
    """
    def __init__(self, kwargs_ce, method='model_01', separate=True):
        """Initializes a Corpus Encoder with the given method.

        Args:
            method (str): {'hierbert', 'max_pooling', 'bow', 'model_01', 'model_02', ...}
                    Method to use for corpus encoding. Defaults to 'max_pooling'.
            separate (bool, optional): Boolean that indicates whether to create
                    a separate encoder for ECB and for FED. Defaults to True.
            dropout (float, optional): The dropout probability. Defaults to 0.
        """
        super(CorpusEncoder, self).__init__()
        self.method = method
        self.separate=separate

        if self.method=='bow':
            self.corpus_emb_dim = 1 * (1 + int(separate))
            # self.encoder = Model()
        elif self.method=='max_pooling':
            self.corpus_emb_dim = 1 * (1 + int(separate))
            # self.encoder = Model()
        elif self.method=='hierbert':
            # https://huggingface.co/kiddothe2b/hierarchical-transformer-I3-mini-1024
            self.corpus_emb_dim = 1 * (1 + int(separate))
            # self.encoder = Model()
        elif self.method=='model_03':
            if not separate:
                self.encoder = CorpusEncoder03(**kwargs_ce)
                self.encoder_ecb = None
                self.encoder_fed = None
                self.corpus_emb_dim = self.encoder.corpus_emb_dim
            else:
                self.encoder = None
                self.encoder_ecb = CorpusEncoder03(**kwargs_ce)
                self.encoder_fed = CorpusEncoder03(**kwargs_ce)
                self.corpus_emb_dim = 2*self.encoder_ecb.corpus_emb_dim
        elif self.method is None:
            self.corpus_emb_dim = 0
                

    def forward(self, x, x_masks):
        """_summary_

        Args:
            x (tuple(Tensor)): Tuple of length either 1 or 2 of tensors of same size.
                If separate is True, the tuple should be of length 2 and contain
                tensors for the tokens of each corpus (ECB and FED respectively).
            x_masks (tuple(Tensor)): Tuple of length either 1 or 2 of tensors of same size.
                If separate is True, the tuple should be of length 2 and contain
                tensors for the attention masks of each corpus (ECB and FED respectively).

        Returns:
            Tensor: Output Tensor of size [batch_size, self.corpus_emb_dim].
        """
        if self.method=='bow':
            # x = ...
            # x_masks = ...
            pass
        elif self.method=='max_pooling':
            # x = ...
            # x_masks = ...
            pass
        elif self.method=='hierbert':
            # x = ...
            # x_masks = ...
            pass
        elif self.method=='model_01':
            pass
        elif self.method is None:
            return None
        if self.separate:
            x_ecb = self.encoder_ecb(x[0], x_masks[0])
            x_fed = self.encoder_fed(x[1], x_masks[1])
            out = torch.cat([x_ecb, x_fed], dim=1).float()
        else:
            out = self.encoder(x[0], x_masks[0])
        return out

class MyModel(nn.Module):
    """
    Custom model using the framework stated above, with one corpus encoding concatenated with the
    nontextual features, followed by a MLP.

    One can process the nontextual features with a pipeline, for instance a CNN.
    """
    def __init__(self, method, kwargs_nontext, kwargs_classification, kwargs_ce, separate=True):
        """_summary_

        Args:
            has_nontext_pipeline (bool, optional): Whether to apply a nontextual network on the inputs.
                Defaults to False.
            nontext_dim (int, optional): Number of non-textual features before concatenation. Defaults to 19.
                If has_nontext_pipeline is False, this will be forced to 19.
            method (str): {'hierbert', 'max_pooling', 'bow'} Method to use for corpus encoding.
                    Defaults to 'max_pooling'.
            separate (bool, optional): Boolean that indicates whether to create
                    a separate encoder for ECB and for FED. Defaults to True.
            layers (int, optional): Number of layers to use in the classification head. Defaults to 3.
            dropout (float, optional): The dropout probability. Defaults to 0.
        """

        super(MyModel, self).__init__()
        self.method = method

        self.nontext_network = NontextualNetwork(**kwargs_nontext)
        self.nontext_dim = self.nontext_network.output_dim

        self.corpus_encoder = CorpusEncoder(kwargs_ce, method=method, separate=separate,)

        corpus_emb_dim = self.corpus_encoder.corpus_emb_dim
        
        self.classifier = ClassificationHead(**kwargs_classification)
    
    def forward(self, x_text, x_masks, x_nontext):
        """Forward method for the general framework.

        Args:
            x_text (torch.Tensor): _description_
            x_masks (torch.Tensor): _description_
            x_nontext (torch.Tensor): Tensor for the nontextual features.

        Returns:
            torch.Tensor: Probability that the sample is of a positive class.
        """

        # TODO: Text encoding
        if self.method=='bow':
            pass
        elif self.method=='max_pooling':
            pass
        elif self.method=='hierbert':
            pass
        # Temp

        x_nontext = self.nontext_network(x_nontext)

        if self.method is None:
            x_corpus = None
        else:
            x_corpus = self.corpus_encoder(x_text, x_masks)

        # Downstream classification
        out = self.classifier(x_corpus, x_nontext)
        return out