"""Offline document question answering over public chip-design / verification documents.

Local embeddings (bge-m3) and a local Qwen, both served on 127.0.0.1; no network at query time. An answer is shown
only with citations that the program has matched against the cited passage; otherwise the answer is "not found".
"""
