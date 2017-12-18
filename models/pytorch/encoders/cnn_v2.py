#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""CNN encoder."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import torch.nn as nn

from models.pytorch.encoders.cnn_utils import ConvOutSize


class CNNEncoder(nn.Module):
    """CNN encoder.
    Args:
        input_size (int): the dimension of input features
        conv_channels (list, optional):
        conv_kernel_sizes (list, optional):
        conv_strides (list, optional):
        poolings (list, optional):
        dropout (float): the probability to drop nodes
        parameter_init (float): the range of uniform distribution to
            initialize weight parameters (>= 0)
        activation (string, optional): relu or prelu or hard_tanh
        use_cuda (bool, optional): if True, use GPUs
        batch_norm (bool, optional):
    """

    def __init__(self,
                 input_size,
                 conv_channels,
                 conv_kernel_sizes,
                 conv_strides,
                 poolings,
                 dropout,
                 parameter_init,
                 activation='relu',
                 use_cuda=False,
                 batch_norm=False):

        super(CNNEncoder, self).__init__()

        self.input_size = input_size
        self.input_channels = 3
        self.input_freq = input_size // self.input_channels

        assert input_size % self.input_channels == 0
        assert len(conv_channels) > 0
        assert len(conv_channels) == len(conv_kernel_sizes)
        assert len(conv_kernel_sizes) == len(conv_strides)
        assert len(conv_strides) == len(poolings)

        convs = []
        in_c = 1
        in_freq = input_size
        for i in range(len(conv_channels)):

            # Conv
            conv = nn.Conv2d(
                in_channels=in_c,
                out_channels=conv_channels[i],
                kernel_size=tuple(conv_kernel_sizes[i]),
                stride=tuple(conv_strides[i]),
                # padding=(conv_kernel_sizes[i][0], conv_kernel_sizes[i][1]),
                padding=(0, 0),
                bias=not batch_norm)
            convs.append(conv)
            in_freq = math.floor(
                (in_freq + 2 * conv.padding[0] - conv.kernel_size[0]) / conv.stride[0] + 1)

            # Activation
            if activation == 'relu':
                convs.append(nn.ReLU())
            elif activation == 'prelu':
                convs.append(nn.PReLU(num_parameters=1, init=0.2))
            elif activation == 'hard_tanh':
                convs.append(nn.Hardtanh(min_val=0, max_val=20, inplace=True))
            else:
                raise NotImplementedError

            # Max Pooling
            if len(poolings[i]) > 0:
                pool = nn.MaxPool2d(
                    kernel_size=(poolings[i][0], poolings[i][0]),
                    stride=(poolings[i][0], poolings[i][1]),
                    padding=(1, 1))
                convs.append(pool)
                in_freq = math.floor(
                    (in_freq + 2 * pool.padding[0] - pool.kernel_size[0]) / pool.stride[0] + 1)

            # Batch Normalization
            if batch_norm:
                convs.append(nn.BatchNorm2d(conv_channels[i]))
                # TODO: compare BN before ReLU and after ReLU

            convs.append(nn.Dropout(p=dropout))
            in_c = conv_channels[i]

        self.conv = nn.Sequential(*convs)

        self.conv_out_size = ConvOutSize(self.conv)
        self.output_size = conv_channels[-1] * in_freq

    def forward(self, inputs):
        """Forward computation.
        Args:
            inputs (FloatTensor): A tensor of size `[B, T, input_size]`
        Returns:
            outputs (FloatTensor): A tensor of size `[B, T', feature_dim]`
        """
        batch_size, max_time, input_size = inputs.size()

        assert input_size == self.input_freq * self.input_channels

        # Reshape to 4D tensor
        inputs = inputs.transpose(1, 2).contiguous()
        inputs = inputs.unsqueeze(dim=1)
        # NOTE: inputs: `[B, in_ch, freq, time]`

        outputs = self.conv(inputs)
        # NOTE: outputs: `[B, out_ch, new_freq, new_time]`

        # Collapse feature dimension
        output_channels, freq, time = outputs.size()[1:]
        outputs = outputs.transpose(1, 3).contiguous()
        outputs = outputs.view(
            batch_size, time, freq * output_channels)

        return outputs