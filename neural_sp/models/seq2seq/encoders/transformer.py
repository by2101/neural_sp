#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Kyoto University (Hirofumi Inaguma)
#  Apache 2.0  (http://www.apache.org/licenses/LICENSE-2.0)

"""Self-attention encoder for Transformer."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging
import torch.nn as nn

from neural_sp.models.modules.linear import LinearND
from neural_sp.models.modules.transformer import SublayerConnection
from neural_sp.models.modules.transformer import PositionwiseFeedForward
from neural_sp.models.modules.transformer import PositionalEncoding
from neural_sp.models.seq2seq.encoders.conv import ConvEncoder
from neural_sp.models.seq2seq.decoders.multihead_attention import MultiheadAttentionMechanism

logger = logging.getLogger("training")


class TransformerEncoder(nn.Module):
    """Transformer encoder.

    Args:
        input_dim (int): dimension of input features (freq * channel)
        attn_type (str): type of attention
        attn_n_heads (int): number of heads for multi-head attention
        n_layers (int): number of blocks
        d_model (int): dimension of keys/values/queries in
                   MultiheadAttentionMechanism, also the input size of
                   the first-layer of the PositionwiseFeedForward
        d_ff (int): dimension of the second layer of the PositionwiseFeedForward
        pe_type (str): concat or add or learn or False
        dropout_in (float): dropout probability for input-hidden connection
        dropout (float): dropout probabilities for linear layers
        dropout_att (float): dropout probabilities for attention distributions
        layer_norm_eps (float):
        last_proj_dim (int): dimension of the last projection layer
        n_stacks (int): number of frames to stack
        n_splices (int): frames to splice. Default is 1 frame.
        conv_in_channel (int): number of channels of input features
        conv_channels (int): number of channles in the CNN blocks
        conv_kernel_sizes (list): size of kernels in the CNN blocks
        conv_strides (list): number of strides in the CNN blocks
        conv_poolings (list): size of poolings in the CNN blocks
        conv_batch_norm (bool): apply batch normalization only in the CNN blocks
        conv_residual (bool): add residual connection between each CNN block
        conv_bottleneck_dim (int): dimension of the bottleneck layer between CNN and self-attention layers
        param_init (float): only for CNN layers before Transformer layers

    """

    def __init__(self,
                 input_dim,
                 attn_type,
                 attn_n_heads,
                 n_layers,
                 d_model,
                 d_ff,
                 pe_type,
                 dropout_in=0,
                 dropout=0,
                 dropout_att=0,
                 layer_norm_eps=1e-6,
                 last_proj_dim=0,
                 n_stacks=1,
                 n_splices=1,
                 conv_in_channel=1,
                 conv_channels=0,
                 conv_kernel_sizes=[],
                 conv_strides=[],
                 conv_poolings=[],
                 conv_batch_norm=False,
                 conv_residual=False,
                 conv_bottleneck_dim=0,
                 param_init=0.1):

        super(TransformerEncoder, self).__init__()

        self.d_model = d_model
        self.pe_type = pe_type

        # Setting for CNNs before RNNs
        if conv_channels:
            channels = [int(c) for c in conv_channels.split('_')] if len(conv_channels) > 0 else []
            kernel_sizes = [[int(c.split(',')[0].replace('(', '')), int(c.split(',')[1].replace(')', ''))]
                            for c in conv_kernel_sizes.split('_')] if len(conv_kernel_sizes) > 0 else []
            strides = [[int(c.split(',')[0].replace('(', '')), int(c.split(',')[1].replace(')', ''))]
                       for c in conv_strides.split('_')] if len(conv_strides) > 0 else []
            poolings = [[int(c.split(',')[0].replace('(', '')), int(c.split(',')[1].replace(')', ''))]
                        for c in conv_poolings.split('_')] if len(conv_poolings) > 0 else []
        else:
            channels = []
            kernel_sizes = []
            strides = []
            poolings = []
            logger.warning('Subsampling is automatically ignored because CNN layers are used before RNN layers.')

        if len(channels) > 0:
            assert n_stacks == 1 and n_splices == 1
            self.conv = ConvEncoder(input_dim,
                                    in_channel=conv_in_channel,
                                    channels=channels,
                                    kernel_sizes=kernel_sizes,
                                    strides=strides,
                                    poolings=poolings,
                                    dropout=0,
                                    batch_norm=conv_batch_norm,
                                    residual=conv_residual,
                                    bottleneck_dim=d_model,
                                    param_init=param_init)
            self._output_dim = self.conv.output_dim
        else:
            self._output_dim = input_dim * n_splices * n_stacks
            self.conv = None

            self.embed = LinearND(self._output_dim, d_model,
                                  dropout=0)  # NOTE: do not apply dropout here

        if pe_type:
            self.pos_emb = PositionalEncoding(d_model, dropout_in, pe_type)
        self.norm_in = nn.LayerNorm(d_model, eps=layer_norm_eps)

        # Self-attention layers
        self.layers = nn.ModuleList(
            [TransformerEncoderBlock(d_model, d_ff, attn_type, attn_n_heads,
                                     dropout, dropout_att, layer_norm_eps) for l in range(n_layers)])
        self.norm_top = nn.LayerNorm(d_model, eps=layer_norm_eps)

        if last_proj_dim != self.output_dim:
            self.bridge = LinearND(self._output_dim, last_proj_dim, dropout=dropout)
            self._output_dim = last_proj_dim
        else:
            self.bridge = None
            self._output_dim = d_model

        # Initialize parameters
        self.reset_parameters()

    @property
    def output_dim(self):
        return self._output_dim

    def reset_parameters(self, param_init):
        """Initialize parameters with xavier_uniform style."""
        logger = logging.getLogger('training')
        logger.info('===== Initialize %s =====' % self.__class__.__name__)
        for n, p in self.named_parameters():
            if 'conv' in n:
                continue  # for CNN layers before Transformer layers
            if p.dim() == 1:
                nn.init.constant_(p, val=0)  # bias
                logger.info('Initialize %s with %s / %.3f' % (n, 'constant', 0))
            elif p.dim() == 2:
                if 'embed' in n:
                    nn.init.normal_(p, mean=0, std=self.d_model**-0.5)
                    logger.info('Initialize %s with %s / %.3f' % (n, 'normal', self.d_model**-0.5))
                else:
                    nn.init.xavier_uniform_(p, gain=1.0)
                    logger.info('Initialize %s with %s / %.3f' % (n, 'xavier_uniform', param_init))
            else:
                raise ValueError

    def forward(self, xs, xlens, task):
        """Forward computation.

        Args:
            xs (FloatTensor): `[B, T, input_dim]`
            xlens (list): `[B]`
            task (str): not supported now
        Returns:
            eouts (dict):
                xs (FloatTensor): `[B, T, d_model]`
                xlens (list): `[B]`

        """
        eouts = {'ys': {'xs': None, 'xlens': None},
                 'ys_sub1': {'xs': None, 'xlens': None},
                 'ys_sub2': {'xs': None, 'xlens': None}}

        if self.conv is None:
            xs = self.embed(xs) * (self.d_model ** 0.5)
        else:
            # Path through CNN blocks before RNN layers
            xs, xlens = self.conv(xs, xlens)

        # Positional encoding & layer normalization
        if self.pe_type:
            xs = self.pos_emb(xs)
        xs = self.norm_in(xs)

        for i in range(len(self.layers)):
            xs, xx_aw = self.layers[i](xs, xlens)
        xs = self.norm_top(xs)

        # Bridge layer
        if self.bridge is not None:
            xs = self.bridge(xs)

        eouts['ys']['xs'] = xs
        eouts['ys']['xlens'] = xlens
        return eouts


class TransformerEncoderBlock(nn.Module):
    """A single layer of the transformer encoder.

    Args:
        d_model (int): dimension of keys/values/queries in
                   MultiheadAttentionMechanism, also the input size of
                   the first-layer of the PositionwiseFeedForward
        d_ff (int): second-layer of the PositionwiseFeedForward
        attn_type (str):
        attn_n_heads (int): number of heads for multi-head attention
        dropout (float): dropout probabilities for linear layers
        dropout_att (float): dropout probabilities for attention distributions
        layer_norm_eps (float):

    """

    def __init__(self,
                 d_model,
                 d_ff,
                 attn_type,
                 attn_n_heads,
                 dropout,
                 dropout_att,
                 layer_norm_eps):
        super(TransformerEncoderBlock, self).__init__()

        # self-attention
        self.self_attn = MultiheadAttentionMechanism(key_dim=d_model,
                                                     query_dim=d_model,
                                                     attn_dim=d_model,
                                                     n_heads=attn_n_heads,
                                                     dropout=dropout_att)
        self.add_norm_self_attn = SublayerConnection(d_model, dropout, layer_norm_eps)

        # feed-forward
        self.ff = PositionwiseFeedForward(d_model, d_ff, dropout)
        self.add_norm_ff = SublayerConnection(d_model, dropout, layer_norm_eps)

    def forward(self, xs, xlens):
        """Transformer encoder layer definition.

        Args:
            xs (FloatTensor): `[B, T, d_model]`
            xlens (list): `[B]`
        Returns:
            xs (FloatTensor): `[B, T, d_model]`
            xx_aw (FloatTensor):

        """
        # self-attention
        xs, xx_aw = self.add_norm_self_attn(xs, sublayer=lambda xs: self.self_attn(
            key=xs, key_lens=xlens, value=xs, query=xs))
        self.self_attn.reset()

        # position-wise feed-forward
        xs = self.add_norm_ff(xs, sublayer=lambda xs: self.ff(xs))
        return xs, xx_aw
