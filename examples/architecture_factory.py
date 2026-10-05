"""In the model environment: naia arch capture --factory examples.architecture_factory:build --output graph.json --trace."""


def build():
    import torch
    model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.ReLU(), torch.nn.Linear(8, 2))
    return model, (torch.zeros(1, 4),), {}
