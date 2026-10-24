"""Operations tooling for the local model service: layered health, log scan, capacity probe, regression gate, releases, config validation.

Three checks are kept separate on purpose: a process can be running while the API is stuck,
and the API can answer while the model is wrong, slow, or partly on the CPU.
"""
