from decision_gateway import RoutedResponse

# A response as OpenRouter returned it for Jev 1.13 (2026-10-16).
JEV = {
    "answers": {"q": {"noul": 0.15, "type": "noul"}},
    "id": "gen-dec-1792159364-1X2z6rsClNbdUvpxHax0",
    "model": "typesafe/jev-1.13-20260917",
    "provider": "TypeSafe",
    "usage": {"cost": 1.2768e-05, "input_tokens": 304, "output_tokens": 20},
}


def test_routed_response_keeps_fields_beyond_the_api() -> None:
    response = RoutedResponse.model_validate(JEV)
    assert response.model == "typesafe/jev-1.13-20260917"
    assert response.nouls["q"].noul == 0.15
    assert response.model_extra == {"id": "gen-dec-1792159364-1X2z6rsClNbdUvpxHax0", "provider": "TypeSafe"}
