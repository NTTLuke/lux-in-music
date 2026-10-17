# YuE2 license review

Reviewed on 2026-10-10 using the original project's published terms.

The [official README](https://github.com/multimodal-art-projection/YuE#license)
and [MODEL_LICENSE](https://github.com/multimodal-art-projection/YuE/blob/main/MODEL_LICENSE)
describe CC BY-NC 4.0 **with additional individual creator permission** for
YuE2-3B, YuE2-Vae and YuE2-Vae-legacy. Under that permission, personal users,
content creators and musicians acting individually can generate and monetize
outputs, including licensing work to clients, without fees or royalties to the
model authors. Credit on generated outputs is optional. The full terms also
include responsible-use conditions and third-party rights requirements.

Companies wishing to use the weights commercially must contact the authors
about a commercial license. This permission does not authorize selling or
commercially redistributing the model weights. The repository code has its own
[Apache 2.0 license](https://github.com/multimodal-art-projection/YuE/blob/main/LICENSE).

The [GGUF publisher's model card](https://huggingface.co/audio-cpp/Yue2-3B-GGUF#license)
and [Hugging Face weight license](https://huggingface.co/m-a-p/YuE2-3B/blob/main/LICENSE)
still display the base CC BY-NC 4.0 terms. The catalog records the pinned base
artifact terms and separately links the additional creator permission at
[its reviewed source revision](https://github.com/multimodal-art-projection/YuE/blob/cbb3b060725ddd95ac6e6237cfb709e153da5988/MODEL_LICENSE).
Do not replace the base identifier with Apache 2.0 or describe all commercial
uses as authorized. Read both the artifact terms and the additional permission.

# EmbeddingGemma 2 license review

Reviewed on 2026-10-17 for the optional Vibe model at revision
`c3f2237ce16fe33d1bb9dab8692c29c79865bdeb`.

The [model card at that revision](https://huggingface.co/google/embeddinggemma-2/blob/c3f2237ce16fe33d1bb9dab8692c29c79865bdeb/README.md)
declares `apache-2.0` and links the [Gemma 4 license](https://ai.google.dev/gemma/docs/gemma_4_license),
which is the Apache License 2.0. EmbeddingGemma 2 is built on Gemma 4. The
[Gemma Terms of Use](https://ai.google.dev/gemma/terms) state that Gemma 4
models use the Gemma 4 license instead. Their appendix lists "EmbeddingGemma"
without a version; that refers to the earlier model, not this revision. Do not
add the Gemma Terms or their Prohibited Use Policy to this model's catalog entry
unless the upstream card changes at a new pinned revision.
