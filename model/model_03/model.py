import torch
import torch.nn as nn
from transformers import DistilBertTokenizer, DistilBertModel


torch.set_default_dtype(torch.float32)

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

class AttentionWithContext(nn.Module):
    """
    Follows the work of Yang et al. [https://www.cs.cmu.edu/~diyiy/docs/naacl16.pdf]
    "Hierarchical Attention Networks for Document Classification"
    by using a context vector to assist the attention
    # Input shape
        3D tensor with shape: `(samples, steps, features)`.
    # Output shape
        2D tensor with shape: `(samples, features)`.
    """
    
    def __init__(self, input_shape, return_coefficients=False, bias=True):
        super(AttentionWithContext, self).__init__()
        self.return_coefficients = return_coefficients

        self.W = nn.Linear(input_shape, input_shape, bias=bias)
        self.tanh = nn.Tanh()
        self.u = nn.Linear(input_shape, 1, bias=False)

        self.init_weights()

    def init_weights(self):
        initrange = 0.1
        self.W.weight.data.uniform_(-initrange, initrange)
        self.W.bias.data.uniform_(-initrange, initrange)
        self.u.weight.data.uniform_(-initrange, initrange)
    
    def generate_square_subsequent_mask(self, sz):
        # do not pass the mask to the next layers
        mask = (torch.triu(torch.ones(sz, sz)) == 1).transpose(0, 1)
        mask = (
            mask.float()
            .masked_fill(mask == 0, float("-inf"))
            .masked_fill(mask == 1, float(0.0))
        )
        return mask
    
    def forward(self, x, mask=None):
        # x has shape: (samples, steps, features)
        # mask has size (samples, steps, 1)
        
        uit = self.W(x) # fill the gap # compute uit = W . x  where x represents ht
        # uit is then of size (samples, steps, features) (Linear only modifies the last dimension)
        uit = self.tanh(uit)

        ait = self.u(uit)
        # ait is of size (samples, steps, 1)
        a = torch.exp(ait)
        
        # apply mask after the exp. will be re-normalized next
        if mask is not None:
            #TODO: Treat case if all masks are False.
            # Not impossible if all inputs are invalid (example: blank inputs)
            a = a*mask.float()
        
        # in some cases especially in the early stages of training the sum may be almost zero
        # and this results in NaN's. A workaround is to add a very small positive number ε to the sum.
        eps = 1e-9
        a = a / (torch.sum(a, axis=1, keepdim=True) + eps)
        weighted_input = torch.sum(a * x, axis=1) ### fill the gap ### # compute the attentional vector
        if self.return_coefficients:
            return weighted_input, a ### [attentional vector, coefficients] ### use torch.sum to compute s
        else:
            return weighted_input ### attentional vector only ###
        
class AttentionBiGRU(nn.Module):
    def __init__(self, input_shape, output_shape_2, dropout=0, bias=True):
        super(AttentionBiGRU, self).__init__()
        self.dropout = nn.Dropout(dropout)
        self.bigru = nn.GRU(input_size=input_shape,
                          hidden_size=output_shape_2,
                          num_layers=1,
                          bias=bias,
                          batch_first=True,
                          bidirectional=True)
        self.attention = AttentionWithContext(2*output_shape_2, return_coefficients=False, bias=bias)

    def forward(self, x, mask=None):
        x, _ = self.bigru(x)
        x = self.dropout(x)
        x = self.attention(x, mask)
        return x

class DocumentEncoder(nn.Module):
    def __init__(self, hidden_dim = 64, bias=True, dropout=.5):
        super(DocumentEncoder, self).__init__()
        self.text_encoder = DistilBertModel.from_pretrained("distilbert-base-uncased")
        self.dropout = nn.Dropout(dropout)
    def forward(self, x, attention_mask=None):
        # Get a word embedding first. x is of shape (samples, steps=512)
        # attention_mask is of same size.
        x = self.text_encoder(x, attention_mask=attention_mask).last_hidden_state
        # x needs to have shape: (samples, steps=512, features=768)
        # the mask needs to have shape: (samples, steps=512, 1)
        # To retrieve the embedding of the CLS token, we will just take the first step
        # of every document.
        x = x[:, 0, :]
        x = self.dropout(x)
        # x needs to have shape: (samples, features=768)
        # x is now of size (samples, features=768) and represents a document.
        return x

class CorpusEncoder(nn.Module):
    def __init__(self, bias=True, dropout=.5):
        super(CorpusEncoder, self).__init__()
        self.doc_encoder = DocumentEncoder(bias=bias)
        self.W = nn.Linear(in_features=768, out_features=32)
        self.corpus_emb_dim = 32
        self.dropout = nn.Dropout(dropout)
    
    def forward(self, x, attention_mask=None):
        # Get a document embedding first.
        # x and attention_mask are of size: (samples, nb_docs, steps=512)
        # We can reshape this into (samples * nb_docs, steps=512)
        batch_size, nb_docs = x.size(0), x.size(1)
        x = x.view(batch_size * nb_docs, -1)
        attention_mask_ = attention_mask.view(batch_size * nb_docs, -1)
        # print("mask : ", attention_mask.size())
        # print("Encode document")
        x = self.doc_encoder(x, attention_mask_)
        # x is now in shape (samples * nb_docs, features=768)
        x = x.view(batch_size, nb_docs, -1)
        # x is once again in shape (samples, nb_docs, features=768)
        # We reduce the nb of docs with max pooling.

        # Note : About Corpus encoding
        # In order to filter out empty entries, we can use the previous attention mask.
        # The original mask is of size (batch_size, steps, 512) in the form:
        # [
        # [[1, 1, 1, 1, ..., 1, 1, 1, 1],
        # [1, 1, 1, 1, ..., 1, 1, 1, 1]
        # [1, 1, 0, 0, ..., 0, 0, 0, 0],
        # [1, 1, 0, 0, ..., 0, 0, 0, 0]],
        # ...,
        # ]
        # Therefore, we can filter the useless entries by using a mask
        # sum > 2. The new mask will then be of size (batch_size, steps, 1)
        # [
        # [[True],
        #  [True]
        #  [False],
        #  [False]],
        # ...,
        # ]
        # print("Encode corpus")
        # attention_mask = torch.sum(attention_mask, dim=-1, keepdim=True).ge(3)
        
        # Max pooling ([0] to get values only, we don't care about indices)
        # We set the masked entries to minus infinity, so that they are discarded by max pooling.
        x = torch.max(x, dim=1)[0]



        # x is now of size (samples, features=768)
        x = self.W(x)
        # x is now of size (samples, features=32) and represents a corpus.
        return x