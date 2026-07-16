import torch
import torchaudio

def mel_spectrogram(
    audio,
    n_fft=1920,
    num_mels=80,
    sampling_rate=24000,
    hop_size=480,
    win_size=1920,
    fmin=0,
    fmax=None,
    center=False,
):
    mel_transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=sampling_rate,
        n_fft=n_fft,
        win_length=win_size,
        hop_length=hop_size,
        n_mels=num_mels,
        f_min=fmin,
        f_max=fmax,
        center=center,
        pad_mode="reflect",
        power=2.0,
        norm="slaney",
        mel_scale="slaney",
    )
    return mel_transform(audio)
