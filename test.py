import torch

print("PyTorch:", torch.__version__)
print("CUDA cua PyTorch:", torch.version.cuda)
print("GPU:", torch.cuda.get_device_name(0))
print("Compute Capability:", torch.cuda.get_device_capability(0))
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    x = torch.randn(1000, 1000, device="cuda")
    y = x @ x
    print("GPU computation: OK")