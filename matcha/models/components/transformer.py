import torch
import torch.nn as nn
from diffusers.models.attention import BasicTransformerBlock as DiffusersBasicTransformerBlock

class BasicTransformerBlock(DiffusersBasicTransformerBlock):
    def __init__(self, dim, num_attention_heads, attention_head_dim, dropout=0.0, activation_fn="geglu", **kwargs):
        super().__init__(
            dim=dim,
            num_attention_heads=num_attention_heads,
            attention_head_dim=attention_head_dim,
            dropout=dropout,
            activation_fn=activation_fn,
        )
