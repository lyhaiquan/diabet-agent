import torch
from diacare.model import MLP


def test_mlp_output_shape():
    model = MLP(21)
    out = model(torch.zeros(5, 21))
    assert out.shape == (5,)
