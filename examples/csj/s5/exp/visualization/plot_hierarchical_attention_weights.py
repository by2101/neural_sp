#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Plot hierarchical model's attention weights (CSJ corpus)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import join, abspath, isdir
import sys
import argparse
import shutil

sys.path.append(abspath('../../../'))
from models.load_model import load
from examples.csj.s5.exp.dataset.load_dataset_hierarchical import Dataset
from utils.io.labels.character import Idx2char
from utils.io.labels.word import Idx2word
from utils.directory import mkdir_join, mkdir
from utils.visualization.attention import plot_hierarchical_attention_weights
from utils.config import load_config

parser = argparse.ArgumentParser()
parser.add_argument('--model_path', type=str,
                    help='path to the model to evaluate')
parser.add_argument('--epoch', type=int, default=-1,
                    help='the epoch to restore')
parser.add_argument('--eval_batch_size', type=int, default=1,
                    help='the size of mini-batch in evaluation')
parser.add_argument('--beam_width', type=int, default=1,
                    help='beam_width (int, optional): beam width for beam search.' +
                    ' 1 disables beam search, which mean greedy decoding.')
parser.add_argument('--max_decode_len', type=int, default=60,
                    help='the length of output sequences to stop prediction when EOS token have not been emitted')
parser.add_argument('--max_decode_len_sub', type=int, default=150,
                    help='the length of output sequences to stop prediction when EOS token have not been emitted')
parser.add_argument('--data_save_path', type=str, help='path to saved data')


def main():

    args = parser.parse_args()

    # Load a config file (.yml)
    params = load_config(join(args.model_path, 'config.yml'), is_eval=True)

    # Load dataset
    test_data = Dataset(
        data_save_path=args.data_save_path,
        backend=params['backend'],
        input_channel=params['input_channel'],
        use_delta=params['use_delta'],
        use_double_delta=params['use_double_delta'],
        data_type='eval1',
        # data_type='eval2',
        # data_type='eval3',
        data_size=params['data_size'],
        label_type=params['label_type'], label_type_sub=params['label_type_sub'],
        batch_size=args.eval_batch_size, splice=params['splice'],
        num_stack=params['num_stack'], num_skip=params['num_skip'],
        sort_utt=True, reverse=True, tool=params['tool'])

    params['num_classes'] = test_data.num_classes
    params['num_classes_sub'] = test_data.num_classes_sub

    # Load model
    model = load(model_type=params['model_type'],
                 params=params,
                 backend=params['backend'])

    # Restore the saved parameters
    model.load_checkpoint(save_path=args.model_path, epoch=args.epoch)

    # GPU setting
    model.set_cuda(deterministic=False, benchmark=True)

    # Visualize
    plot(model=model,
         dataset=test_data,
         beam_width=args.beam_width,
         max_decode_len=args.max_decode_len,
         max_decode_len_sub=args.max_decode_len_sub,
         eval_batch_size=args.eval_batch_size,
         save_path=mkdir_join(args.model_path, 'att_weights'))
    # save_path=None)


def plot(model, dataset, beam_width, max_decode_len, max_decode_len_sub,
         eval_batch_size=None, save_path=None):
    """Visualize attention weights of Attetnion-based model.
    Args:
        model: model to evaluate
        dataset: An instance of a `Dataset` class
        beam_width: (int): the size of beam
        max_decode_len (int): the length of output sequences
            to stop prediction when EOS token have not been emitted.
        max_decode_len_sub (int):
        eval_batch_size (int, optional): the batch size when evaluating the model
        save_path (string, optional): path to save attention weights plotting
    """
    # Set batch size in the evaluation
    if eval_batch_size is not None:
        dataset.batch_size = eval_batch_size

    # Clean directory
    if save_path is not None and isdir(save_path):
        shutil.rmtree(save_path)
        mkdir(save_path)

    map_fn_main = Idx2word(dataset.vocab_file_path, return_list=True)
    map_fn_sub = Idx2char(dataset.vocab_file_path_sub, return_list=True)

    for batch, is_new_epoch in dataset:

        # Decode
        best_hyps, aw, perm_idx = model.attention_weights(
            batch['xs'], batch['x_lens'],
            beam_width=beam_width,
            max_decode_len=max_decode_len)
        best_hyps_sub, aw_sub, _ = model.attention_weights(
            batch['xs'], batch['x_lens'],
            beam_width=beam_width,
            max_decode_len=max_decode_len,
            is_sub_task=True)

        for b in range(len(batch['xs'])):

            # Check if the sum of attention weights equals to 1
            # print(np.sum(aw[b], axis=1))

            word_list = map_fn_main(best_hyps[b])
            char_list = map_fn_sub(best_hyps_sub[b])

            speaker = batch['input_names'][b].split('_')[0]

            plot_hierarchical_attention_weights(
                aw[b, :len(word_list), :batch['x_lens'][b]],
                aw_sub[b, :len(char_list), :batch['x_lens'][b]],
                frame_num=batch['x_lens'][b],
                num_stack=dataset.num_stack,
                label_list=word_list,
                label_list_sub=char_list,
                spectrogram=batch['xs'][b, :, :80],
                save_path=mkdir_join(save_path, speaker,
                                     batch['input_names'][b] + '.png'),
                figsize=(40, 8)
            )

        if is_new_epoch:
            break


if __name__ == '__main__':
    main()