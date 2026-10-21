"""Optional numerical contract test, run in the training environment (no downloads)."""

import pytest


def test_action_only_loss_matches_full_masked_causal_loss_and_gradients():
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from resolvelab.training import action_loss

    torch.manual_seed(3)
    config = transformers.Qwen3Config(
        vocab_size=64,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=8,
    )
    model = transformers.Qwen3ForCausalLM(config).eval()
    ids = [10, 11, 12, 20, 21]
    inputs = torch.tensor([ids])
    labels = torch.tensor([[-100, -100, -100, 20, 21]])
    full = model(input_ids=inputs, labels=labels, use_cache=False).loss
    full.backward()
    expected = model.lm_head.weight.grad.clone()
    model.zero_grad()
    sliced = action_loss(model, (ids, 2))
    sliced.backward()
    torch.testing.assert_close(sliced, full)
    torch.testing.assert_close(model.lm_head.weight.grad, expected)
