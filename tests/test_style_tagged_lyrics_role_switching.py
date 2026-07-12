from __future__ import annotations

import pytest

from app.services.ai_chat_service import AiJsonResult
from app.services.global_assistant_service import GlobalAssistantService, SUNO_STYLE_LYRICS_MAX_LENGTH


ROLE_SWITCH_LYRICS = """[Chorus x2 | Repeat Entire Hook Twice | Clear Vocal Role Switching]

[Rough Powerhouse Male Singer | Raspy Full Chest Voice | No Rap]
Ich kann nicht widerstehn,
muss meine Wege gehn...

[Deep Male Rapper | Hard Straight Rap Break | No Melody | No Singing]
Keiner kann mir sagen, was die Zeit für mich bringt,
doch ich laufe immer weiter, bis ich mein Ende find... ich bin.

[Rough Powerhouse Male Singer | Gritty Full-Voice Belting | No Rap]
Stark genug, um steile Wege zu schaffen,
ich werd das Beste draus machen.
Wir werden es schon sehn, es wird gehn!

[Final Chorus x2 | Repeat Entire Hook Twice | Maximum Anthemic Climax]

[Male Singer | Powerful Gritty Belting | No Rap]
Ich kann nicht widerstehn,
muss meine Wege gehn...

[Deep Male Rapper | Aggressive Straight Rap Break | No Melody | No Singing]
Keiner kann mir sagen, was die Zeit für mich bringt,
doch ich laufe immer weiter, bis ich mein Ende find... ich bin.

[Male Singer | Climactic Gritty Belting | No Rap]
Stark genug, um steile Wege zu schaffen,
ich werd das Beste draus machen.
Wir werden es schon sehn, es wird gehn!

[End]"""


def _fake_runtime(db, profile_id):
    return (
        "openai",
        "gpt-test",
        "Systemprompt fuer Test",
        [],
        [],
        {"profile_id": None, "temperature": 0.2, "max_output_tokens": 2000},
    )


@pytest.mark.asyncio
async def test_tagged_lyrics_preserves_singer_rapper_switches_and_repeat_markers(monkeypatch, isolated_db_session):
    service = GlobalAssistantService()
    captured_payload = {}

    # Absichtlich fehlerhafte KI-Ausgabe: Der gesamte Chorus wird als Sängerblock
    # zusammengefasst und die lokalen Rapper-Tags sowie x2/Final gehen verloren.
    collapsed = """[Chorus: gritty powerhouse male singer, no rap]
Ich kann nicht widerstehn,
muss meine Wege gehn...

Keiner kann mir sagen, was die Zeit für mich bringt,
doch ich laufe immer weiter, bis ich mein Ende find... ich bin.

Stark genug, um steile Wege zu schaffen,
ich werd das Beste draus machen.
Wir werden es schon sehn, es wird gehn!

[Chorus: gritty powerhouse male singer, no rap]
Ich kann nicht widerstehn,
muss meine Wege gehn...

Keiner kann mir sagen, was die Zeit für mich bringt,
doch ich laufe immer weiter, bis ich mein Ende find... ich bin.

Stark genug, um steile Wege zu schaffen,
ich werd das Beste draus machen.
Wir werden es schon sehn, es wird gehn!

[End]"""

    async def fake_json_task(self, *, provider, model, system_prompt, instruction_payload, profile_options=None):
        captured_payload.update(instruction_payload)
        return AiJsonResult(
            data={
                "tagged_lyrics": collapsed,
                "lyric_vocal_tags": [
                    {"section": "Chorus", "tag": "[Chorus: gritty powerhouse male singer, no rap]"}
                ],
            },
            raw_text="{}",
            raw_response={},
        )

    monkeypatch.setattr(service, "_get_ai_runtime", _fake_runtime)
    monkeypatch.setattr("app.services.global_assistant_service.AiChatService.run_json_task", fake_json_task)

    result = await service.generate_style_tagged_lyrics(
        isolated_db_session,
        lyrics=ROLE_SWITCH_LYRICS,
        suggestion={"title": "Test", "style": "German boom bap, 96 BPM, gritty male vocals"},
    )

    tagged = result["tagged_lyrics"]
    assert len(tagged) <= SUNO_STYLE_LYRICS_MAX_LENGTH
    assert "[Chorus x2 | Repeat Entire Hook Twice | Clear Vocal Role Switching]" in tagged
    assert "[Final Chorus x2 | Repeat Entire Hook Twice | Maximum Anthemic Climax]" in tagged
    assert tagged.count("Male Singer") >= 4
    assert tagged.count("Male Rapper") == 2
    assert tagged.count("No Rap") >= 4
    assert tagged.count("No Singing") == 2
    assert service._lyric_content_lines(tagged) == service._lyric_content_lines(ROLE_SWITCH_LYRICS)
    assert "sichere strukturtreue Vorschau" in result["notes"]
    assert captured_payload["limits"]["tagged_lyrics_max_chars"] == 5000
    assert any("Fasse Sänger und Rapper" in rule for rule in captured_payload["rules"])


@pytest.mark.asyncio
async def test_tagged_lyrics_compacts_noncritical_tags_but_never_lyrics(monkeypatch, isolated_db_session):
    service = GlobalAssistantService()
    long_lyric = "A" * 4550
    original = f"[Verse 1]\n{long_lyric}"
    oversized_candidate = f"[Verse 1: deep male rapper, dry delivery]\n{long_lyric}\n[{'Atmospheric FX ' * 45}]"

    async def fake_json_task(self, *, provider, model, system_prompt, instruction_payload, profile_options=None):
        return AiJsonResult(
            data={"tagged_lyrics": oversized_candidate, "lyric_vocal_tags": []},
            raw_text="{}",
            raw_response={},
        )

    monkeypatch.setattr(service, "_get_ai_runtime", _fake_runtime)
    monkeypatch.setattr("app.services.global_assistant_service.AiChatService.run_json_task", fake_json_task)

    result = await service.generate_style_tagged_lyrics(
        isolated_db_session,
        lyrics=original,
        suggestion={"title": "Test", "style": "German rap, 96 BPM"},
    )

    tagged = result["tagged_lyrics"]
    assert len(tagged) <= 5000
    assert long_lyric in tagged
    assert "Atmospheric FX" not in tagged
    assert service._lyric_content_lines(tagged) == service._lyric_content_lines(original)


@pytest.mark.asyncio
async def test_tagged_lyrics_rejects_input_above_hard_limit(monkeypatch, isolated_db_session):
    service = GlobalAssistantService()
    monkeypatch.setattr(service, "_get_ai_runtime", _fake_runtime)

    with pytest.raises(ValueError, match="maximal 5000 Zeichen"):
        await service.generate_style_tagged_lyrics(
            isolated_db_session,
            lyrics="X" * 5001,
            suggestion={"title": "Test", "style": "German rap, 96 BPM"},
        )


def test_compaction_preserves_essential_role_signatures_and_final_x2():
    service = GlobalAssistantService()
    oversized = ROLE_SWITCH_LYRICS.replace(
        "[Rough Powerhouse Male Singer | Raspy Full Chest Voice | No Rap]",
        "[Rough Powerhouse Male Singer | Raspy Full Chest Voice | Wide Double-Tracked Lead | Long Reverb | Layered Harmonies | No Rap]",
    )
    compacted = service._compact_tagged_lyrics_to_limit(oversized, 900)

    assert len(compacted) <= 900
    assert "Final Chorus x2" in compacted
    assert "Male Rapper" in compacted
    assert "Male Singer" in compacted
    assert "No Rap" in compacted
    assert "No Singing" in compacted
    assert service._lyric_content_lines(compacted) == service._lyric_content_lines(ROLE_SWITCH_LYRICS)


def test_compaction_keeps_meaningful_verse_vocal_tags_instead_of_bare_headers():
    service = GlobalAssistantService()
    verse_lines = "\n".join(f"Zeile {index} bleibt unverändert und trägt den Song weiter." for index in range(1, 33))
    oversized = f"""[Verse 1 | Deep Baritone Male Rap | Straight 4/4 Flow | Even Bar Phrasing | Tight Pocket | Defiant Tone | Dry Close-Mic | No Singing | Additional Decorative Descriptor | Another Decorative Descriptor]
{verse_lines}

[Verse 2 | Deep Male Rap | Straight 4/4 Flow | Controlled Pacing | Tight Pocket | Confident Forward Tone | Dry Close-Mic | No Singing | Additional Decorative Descriptor | Another Decorative Descriptor]
{verse_lines}"""

    assert len(oversized) > 3000
    compacted = service._compact_tagged_lyrics_to_limit(oversized, 3600)

    assert len(compacted) <= 3600
    assert "[Verse 1:" in compacted
    assert "[Verse 2:" in compacted
    assert "Male Rap" in compacted
    assert "No Singing" in compacted
    assert "[Verse 1]" not in compacted
    assert "[Verse 2]" not in compacted
    assert service._lyric_content_lines(compacted) == service._lyric_content_lines(oversized)


def test_build_up_is_recognized_and_generic_unmatched_tags_are_not_prepended():
    service = GlobalAssistantService()
    lyrics = """[Intro]\nIntrozeile\n\n[Build-Up | Male Spoken Word | Direct | No Singing]\nAufbauzeile\n\n[Chorus]\nHookzeile"""
    tags = [
        {"section": "Build-Up", "tag": "[Build-Up: Male Spoken Word, Direct, No Singing]"},
        {"section": "Unbekannter Block", "tag": "[Male Spoken Word | No Melody]"},
    ]

    merged = service._merge_lyric_vocal_tags_into_lyrics(
        lyrics,
        tags,
        preserve_local_directives=True,
    )

    assert service._lyric_section_meta("[Build-Up | Male Spoken Word | Direct | No Singing]")["base"] == "build-up"
    assert merged.startswith("[Intro]")
    assert "[Male Spoken Word | No Melody]\n\n[Intro]" not in merged
    assert "[Build-Up | Male Spoken Word | Direct | No Singing]" in merged
