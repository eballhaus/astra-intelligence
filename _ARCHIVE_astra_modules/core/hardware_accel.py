import torch


def pin_device():
    """Pin device for GPU/Metal inference."""
    if torch.cuda.is_available():
        device = torch.device("cuda")
        torch.set_default_device(device)
        print("[Hardware] CUDA acceleration enabled.")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        torch.set_default_device(device)
        print("[Hardware] Apple Metal acceleration enabled.")
    else:
        print("[Hardware] CPU fallback.")
