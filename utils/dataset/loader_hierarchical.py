#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Base class for loading dataset for the multitask CTC and attention-based model.
   In this class, all data will be loaded at each step.
   You can use the multi-GPU version.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import basename
import math
import numpy as np
from multiprocessing import Process
import time

from utils.dataset.base import Base
from utils.io.inputs.frame_stacking import stack_frame
from utils.io.inputs.splicing import do_splice

# NOTE: Loading numpy is faster than loading htk


class DatasetBase(Base):

    def __init__(self, *args, **kwargs):
        super(DatasetBase, self).__init__(*args, **kwargs)

    def __getitem__(self, index):
        feature = self._load_npy([self.df['input_path'][index]])
        transcript = self.df['transcript'][index]
        transcript_sub = self.df_sub['transcript'][index]
        return (feature, transcript, transcript_sub)

    def make_batch(self, data_indices):
        """
        Args:
            data_indices (np.ndarray):
        Returns:
            inputs: list of input data of size
                `[num_gpus, B, T_in, input_size]`
            labels: list of target labels in the main task, size
                `[num_gpus, B, T_out]`
            labels_sub: list of target labels in the sub task, size
                `[num_gpus, B, T_out_sub]`
            inputs_seq_len: list of length of inputs of size
                `[num_gpus, B]`
            labels_seq_len: list of length of target labels in the main
                task, size `[num_gpus, B]`
            labels_seq_len_sub: list of length of target labels in the sub
                task, size `[num_gpus, B]`
            input_names: list of file name of input data of size
                `[num_gpus, B]`
        """
        # Load dataset in mini-batch
        input_path_list = np.array(self.df['input_path'][data_indices])
        str_indices_list = np.array(self.df['transcript'][data_indices])
        str_indices_list_sub = np.array(
            self.df_sub['transcript'][data_indices])

        if not hasattr(self, 'input_size'):
            if self.save_format == 'numpy':
                self.input_size = self.load_npy(input_path_list[0]).shape[-1]
            elif self.save_format == 'htk':
                self.input_size = self.load_htk(input_path_list[0]).shape[-1]
            else:
                raise TypeError
            self.input_size *= self.num_stack
            self.input_size *= self.splice

        # Compute max frame num in mini-batch
        max_frame_num = max(self.df['frame_num'][data_indices])
        max_frame_num = math.ceil(max_frame_num / self.num_skip)

        # Compute max target label length in mini-batch
        max_seq_len = max(
            map(lambda x: len(x.split(' ')), str_indices_list)) + 2
        max_seq_len_sub = max(
            map(lambda x: len(x.split(' ')), str_indices_list_sub)) + 2
        # NOTE: add <SOS> and <EOS>

        # Initialization
        inputs = np.zeros(
            (len(data_indices), max_frame_num, self.input_size * self.splice),
            dtype=np.float32)
        labels = np.array(
            [[self.pad_value] * max_seq_len] * len(data_indices))
        labels_sub = np.array(
            [[self.pad_value_sub] * max_seq_len_sub] * len(data_indices))
        inputs_seq_len = np.zeros((len(data_indices),), dtype=np.int32)
        labels_seq_len = np.zeros((len(data_indices),), dtype=np.int32)
        labels_seq_len_sub = np.zeros((len(data_indices),), dtype=np.int32)
        input_names = np.array(list(
            map(lambda path: basename(path).split('.')[0],
                np.array(self.df['input_path'][data_indices]))))

        # Set values of each data in mini-batch
        for i_batch in range(len(data_indices)):
            # Load input data
            if self.save_format == 'numpy':
                data_i = self.load_npy(input_path_list[i_batch])
            elif self.save_format == 'htk':
                data_i = self.load_htk(input_path_list[i_batch])
            else:
                raise TypeError

            # Frame stacking
            data_i = stack_frame(data_i, self.num_stack, self.num_skip)
            frame_num = data_i.shape[0]

            # Splicing
            data_i = do_splice(data_i, self.splice, self.num_stack)

            inputs[i_batch, : frame_num, :] = data_i
            inputs_seq_len[i_batch] = frame_num
            if self.is_test:
                labels[i_batch, 0] = self.df['transcript'][data_indices[i_batch]]
                labels_sub[i_batch,
                           0] = self.df_sub['transcript'][data_indices[i_batch]]
                # NOTE: transcript is not tokenized
            else:
                indices = list(map(int, str_indices_list[i_batch].split(' ')))
                indices_sub = list(
                    map(int, str_indices_list_sub[i_batch].split(' ')))
                label_num = len(indices)
                label_num_sub = len(indices_sub)
                if self.model_type == 'hierarchical_attention':
                    labels[i_batch, 0] = self.sos_index
                    labels[i_batch, 1:label_num + 1] = indices
                    labels[i_batch, label_num + 1] = self.eos_index
                    labels_seq_len[i_batch] = label_num + 2
                    # NOTE: include <SOS> and <EOS>

                    labels_sub[i_batch, 0] = self.sos_index_sub
                    labels_sub[i_batch, 1: label_num_sub + 1] = indices_sub
                    labels_sub[i_batch, label_num_sub + 1] = self.eos_index_sub
                    labels_seq_len_sub[i_batch] = label_num_sub + 2
                elif self.model_type == 'hierarchical_ctc':
                    labels[i_batch, 0:label_num] = indices
                    labels_seq_len[i_batch] = label_num

                    labels_sub[i_batch,
                               0: label_num_sub] = indices_sub
                    labels_seq_len_sub[i_batch] = label_num_sub
                else:
                    raise TypeError

        # Now we split the mini-batch data by num_gpus
        # inputs = self.split_per_device(inputs, self.num_gpus)
        # labels = self.split_per_device(labels, self.num_gpus)
        # labels_sub = self.split_per_device(labels_sub, self.num_gpus)
        # inputs_seq_len = self.split_per_device(inputs_seq_len, self.num_gpus)
        # labels_seq_len = self.split_per_device(labels_seq_len, self.num_gpus)
        # labels_seq_len_sub = self.split_per_device(
        #     labels_seq_len_sub, self.num_gpus)
        # input_names = self.split_per_device(input_names, self.num_gpus)

        return inputs, labels, labels_sub, inputs_seq_len, labels_seq_len, labels_seq_len_sub, input_names
