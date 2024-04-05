import logging
from typing import Iterable

from accelerate import Accelerator

import torch.utils.data

from rocket.core.capsule import Capsule, Attributes
from rocket.utils import move, collate


class Dataset(Capsule):
    def __init__(self,
                 dataset: Iterable,
                 statefull: bool = True,
                 accelerator: Accelerator = None,
                 priority: int =1000,
                 **kwargs):
        super().__init__(accelerator=accelerator,
                         statefull=statefull,
                         priority=priority)
        self._dataset = dataset
        self._dataloader = None
        self._active_dataloader = None
        self._iterator = None
        # dataloader args
        self._kwargs = kwargs
        self._kwargs.update(collate_fn=collate)
        # loop indices
        self._batch_idx = 0
        self._total = 0


    def setup(self, attrs: Attributes=None):
        # log setup state
        Capsule.setup(self, attrs=attrs)
        # default torch dataloader
        self._dataloader = torch.utils.data.DataLoader(self._dataset, 
                                                       **self._kwargs)
        # if distributed, prepare it
        self._dataloader = self._accelerator.prepare(self._dataloader)


    def set(self, attrs: Attributes=None):
        # default debug log
        Capsule.set(self, attrs=attrs)
        # if this dataset is in eval mode, does not resume state
        # if state is default, nothing to do
        if torch.is_grad_enabled() and self._batch_idx > 0:
            self._active_dataloader = self._accelerator.skip_first_batches(
                self._dataloader, self._batch_idx
            )
        else:
            self._active_dataloader = self._dataloader
        # total number of iterations left 
        self._total = len(self._active_dataloader)
        # create iterator
        self._iterator = iter(self._active_dataloader)


    def reset(self, attrs: Attributes=None):
        # default debug log
        Capsule.reset(self, attrs=attrs)
        # at the end of an epoch
        # 1. reset batch counter
        self._batch_idx = 0
        # 2. reset total number
        self._total = 0
        # 3. reset iterator
        self._iterator = None


    def launch(self, attrs: Attributes=None):
        # default debug log
        Capsule.launch(self, attrs=attrs)
        # if no attributes provided or 
        # batch has already been created
        # then nothing to do
        if attrs is None or attrs.batch is not None:
            return
        
        # else try to get it
        data = next(self._iterator, None)
        
        if data is None:
            attrs.batch = data
            
            if attrs.looper is not None:
                attrs.looper.terminate = True
                return
        else:
            # move to device
            # if accelerate is properly defined, use it
            device = self._accelerator.device
            attrs.batch = move(data, device)
            
            if attrs.looper is not None:
                # data is provided, continue inner loop
                attrs.looper.terminate = False
            # increase batch counter
            self._batch_idx += 1

    def destroy(self, attrs: Attributes=None):
        # log it for human tracking
        Capsule.destroy(self, attrs=attrs)
        # free dataloader, iterator has been freed in reset()
        self._dataloader = None
        self._active_dataloader = None
        # refresh accelerator state
        self._accelerator._dataloaders.pop()


    def state_dict(self):
        # if (len(self._dataloader) - self._batch_idx) > 0:
            # method for register_for_checkpointing, gather state
        return Attributes(batch_idx=self._batch_idx)
        # return Attributes(batch_idx=0)
    
    def load_state_dict(self, state):
        # method for register_for_checkpointing, load state
        self._batch_idx = state.batch_idx
