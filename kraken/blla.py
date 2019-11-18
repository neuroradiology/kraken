# -*- coding: utf-8 -*-
#
# Copyright 2019 Benjamin Kiessling
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied. See the License for the specific language governing
# permissions and limitations under the License.
"""
kraken.blla
~~~~~~~~~~~~~~

Trainable baseline layout analysis tools for kraken
"""

import json
import torch
import logging
import numpy as np
import pkg_resources
import torch.nn.functional as F

from typing import Tuple, Sequence, List
from scipy.ndimage.filters import (gaussian_filter, uniform_filter,
                                   maximum_filter)

from kraken.lib import morph, sl, vgsl, segmentation, dataset
from kraken.lib.util import pil2array, is_bitonal, get_im_str
from kraken.lib.exceptions import KrakenInputException
from kraken.lib.segmentation import polygonal_reading_order, vectorize_lines, scale_polygonal_lines
from kraken.rpred import rpred
from kraken.serialization import max_bbox

__all__ = ['segment']

logger = logging.getLogger(__name__)


def segment(im,
            text_direction='horizontal-lr',
            mask=None,
            reading_order_fn=polygonal_reading_order,
            model=pkg_resources.resource_filename(__name__, 'blla.mlmodel')):
    """
    Segments a page into text lines using the baseline segmenter.

    Segments a page into text lines and returns the polyline formed by each
    baseline and their estimated environment.

    Args:
        im (PIL.Image): An RGB image.
        text_direction (str): Ignored by the segmenter but kept for
                              serialization.
        mask (PIL.Image): A bi-level mask image of the same size as `im` where
                          0-valued regions are ignored for segmentation
                          purposes. Disables column detection.
        reading_order_fn (function): Function to determine the reading order.
                                     Has to accept a list of tuples (baselines,
                                     polygon) and a text direction (`lr` or
                                     `rl`).
        model (str): A path to a segmentation model.

    Returns:
        {'text_direction': '$dir',
         'type': 'baseline',
         'lines': [
            {'baseline': [[x0, y0], [x1, y1], ..., [x_n, y_n]], 'boundary': [[x0, y0, x1, y1], ... [x_m, y_m]]},
            {'baseline': [[x0, ...]], 'boundary': [[x0, ...]]}
          ]
        }: A dictionary containing the text direction and under the key 'lines'
        a list of reading order sorted baselines (polylines) and their
        respective polygonal boundaries. The last and first point of each
        boundary polygon is connected.

    Raises:
        KrakenInputException if the input image is not binarized or the text
        direction is invalid.
    """
    im_str = get_im_str(im)
    logger.info('Segmenting {}'.format(im_str))

    model = vgsl.TorchVGSLModel.load_model(model)
    model.eval()
    if mask:
        if mask.mode != '1' and not is_bitonal(mask):
            logger.error('Mask is not bitonal')
            raise KrakenInputException('Mask is not bitonal')
        mask = mask.convert('1')
        if mask.size != im.size:
            logger.error('Mask size {} doesn\'t match image size {}'.format(mask.size, im.size))
            raise KrakenInputException('Mask size {} doesn\'t match image size {}'.format(mask.size, im.size))
        logger.info('Masking enabled in segmenter.')
        mask = pil2array(mask)

    batch, channels, height, width = model.input
    transforms = dataset.generate_input_transforms(batch, height, width, channels, 0, valid_norm=False)

    with torch.no_grad():
        logger.debug('Running network forward pass')
        o = model.nn(transforms(im).unsqueeze(0))
    logger.debug('Upsampling network output')
    o = o.squeeze(0).numpy()
#    o = F.interpolate(o, size=im.size[::-1]).squeeze(0).numpy()
    logger.debug('Vectorizing network output')
    baselines = vectorize_lines(o)
    logger.debug('Scaling vectorized lines')
    scale = np.divide(im.size, o.shape[:0:-1])
    baselines = scale_polygonal_lines(baselines, scale)
    logger.debug('Reordering baselines')
    baselines = reading_order_fn(baselines, text_direction[-2:])
    return {'text_direction': text_direction,
            'type': 'baselines',
            'lines': [{'script': 'default', 'baseline': bl, 'boundary': pl} for bl, pl in baselines]}


