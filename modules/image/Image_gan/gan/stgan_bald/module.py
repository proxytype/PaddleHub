# -*- coding:utf-8 -*-
# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import copy
import paddle
import numpy as np
from paddle.inference import Config, create_predictor
from paddlehub.module.module import moduleinfo, serving
from .data_feed import reader
from .processor import postprocess, base64_to_cv2, cv2_to_base64


def check_attribute_conflict(label_batch):
    ''' Based on https://github.com/LynnHo/AttGAN-Tensorflow'''
    attrs = "Bald,Bangs,Black_Hair,Blond_Hair,Brown_Hair,Bushy_Eyebrows,Eyeglasses,Male,Mouth_Slightly_Open,Mustache,No_Beard,Pale_Skin,Young".split(
        ',')

    def _set(label, value, attr):
        if attr in attrs:
            label[attrs.index(attr)] = value

    attr_id = attrs.index('Bald')
    for label in label_batch:
        if attrs[attr_id] != 0:
            _set(label, 0, 'Bangs')

    return label_batch


@moduleinfo(
    name="stgan_bald",
    version="1.1.0",
    summary="Baldness generator",
    author="Arrow, 七年期限，Mr.郑先生_",
    author_email="1084667371@qq.com，2733821739@qq.com",
    type="image/gan")
class StganBald:
    def __init__(self):
        self.default_pretrained_model_path = os.path.join(
            self.directory, "module", "model")
        self._set_config()

    def _set_config(self):
        """
        predictor config setting
        """
        model = self.default_pretrained_model_path+'.pdmodel'
        params = self.default_pretrained_model_path+'.pdiparams'
        cpu_config = Config(model, params)
        cpu_config.disable_glog_info()
        cpu_config.disable_gpu()
        self.cpu_predictor = create_predictor(cpu_config)

        try:
            _places = os.environ["CUDA_VISIBLE_DEVICES"]
            int(_places[0])
            use_gpu = True
            self.place = paddle.CUDAPlace(0)
        except:
            use_gpu = False
            self.place = paddle.CPUPlace()

        if use_gpu:
            gpu_config = Config(model, params)
            gpu_config.disable_glog_info()
            gpu_config.enable_use_gpu(
                memory_pool_init_size_mb=1000, device_id=0)
            self.gpu_predictor = create_predictor(gpu_config)

    def bald(self,
             images=None,
             paths=None,
             data=None,
             use_gpu=False,
             org_labels=[[0., 0., 1., 0., 0., 1., 1., 1., 0., 0., 0., 0., 1.]],
             target_labels=None,
             visualization=True,
             output_dir="bald_output"):
        """
        API for super resolution.

        Args:
            images (list(numpy.ndarray)): images data, shape of each is [H, W, C], the color space is BGR.
            paths (list[str]): The paths of images.
            data (dict): key is 'image', the corresponding value is the path to image.
            use_gpu (bool): Whether to use gpu.
            visualization (bool): Whether to save image or not.
            output_dir (str): The path to store output images.

        Returns:
            res (list[dict]): each element in the list is a dict, the keys and values are:
                save_path (str, optional): the path to save images. (Exists only if visualization is True)
                data (numpy.ndarray): data of post processed image.
        """
        if use_gpu:
            try:
                _places = os.environ["CUDA_VISIBLE_DEVICES"]
                int(_places[0])
            except:
                raise RuntimeError(
                    "Environment Variable CUDA_VISIBLE_DEVICES is not set correctly. If you wanna use gpu, please set CUDA_VISIBLE_DEVICES as cuda_device_id."
                )

        if data and 'image' in data:
            if paths is None:
                paths = list()
            paths += data['image']

        all_data = list()
        for yield_data in reader(images, paths, org_labels, target_labels):
            all_data.append(yield_data)

        total_num = len(all_data)
        res = list()
        outputs = []
        for i in range(total_num):
            image_np = all_data[i]['img']
            org_label_np = [all_data[i]['org_label']]
            target_label_np = [all_data[i]['target_label']]
            for j in range(5):
                if j % 2 == 0:
                    label_trg_tmp = copy.deepcopy(target_label_np)
                    new_i = 0
                    label_trg_tmp[0][new_i] = 1.0 - label_trg_tmp[0][new_i]
                    label_trg_tmp = check_attribute_conflict(
                        label_trg_tmp)
                    change_num = j * 0.02 + 0.3
                    label_org_tmp = list(
                        map(lambda x: ((x * 2) - 1) * change_num, org_label_np))
                    label_trg_tmp = list(
                        map(lambda x: ((x * 2) - 1) * change_num, label_trg_tmp))

                    predictor = self.gpu_predictor if use_gpu else self.cpu_predictor
                    input_names = predictor.get_input_names()
                    input_handle = predictor.get_input_handle(input_names[0])
                    input_handle.copy_from_cpu(image_np.copy())
                    input_handle = predictor.get_input_handle(input_names[1])
                    input_handle.copy_from_cpu(
                        np.array(label_org_tmp).astype('float32'))
                    input_handle = predictor.get_input_handle(input_names[2])
                    input_handle.copy_from_cpu(
                        np.array(label_trg_tmp).astype('float32'))
                    predictor.run()
                    output_names = predictor.get_output_names()
                    output_handle = predictor.get_output_handle(
                        output_names[0])
                    outputs.append(output_handle)

            out = postprocess(
                data_out=outputs,
                org_im=all_data[i]['org_im'],
                org_im_path=all_data[i]['org_im_path'],
                output_dir=output_dir,
                visualization=visualization)
            res.append(out)
        return res

    @serving
    def serving_method(self, images, **kwargs):
        """
        Run as a service.
        """
        images_decode = [base64_to_cv2(image) for image in images]
        results = self.bald(images=images_decode, **kwargs)
        output = {}
        for key, value in results[0].items():
            output[key] = cv2_to_base64(value)

        return output
