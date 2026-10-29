from __future__ import annotations

import sys
import warnings

import torch

from backend.core.config import Settings


def main() -> int:
    device = Settings().values["device"]
    if device.casefold() == "cpu":
        print("CPU diagnostic mode selected explicitly.")
        return 0
    if not torch.cuda.is_available():
        print("CUDA is unavailable. Check the NVIDIA driver and install a compatible PyTorch CUDA wheel.")
        return 1
    try:
        index = int(device)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            props = torch.cuda.get_device_properties(index)
        capability = f"sm_{props.major}{props.minor}"
        supported = torch.cuda.get_arch_list()
    except (ValueError, RuntimeError, AssertionError) as exc:
        print(f"Invalid CUDA device '{device}': {exc}")
        return 1
    print(f"GPU: {props.name} ({capability}); PyTorch {torch.__version__}; CUDA wheel {torch.version.cuda}")
    if props.major >= 10 and capability not in supported:
        print(f"Current PyTorch has no {capability} kernel. Supported: {', '.join(supported)}")
        return 1
    print("CUDA architecture check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
