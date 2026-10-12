"""CLI de Claude Code SIMULADO para pruebas sin red (no es la integración real).

Imita el protocolo ``claude -p --input-format stream-json --output-format stream-json``:
lee el mensaje de usuario por stdin y emite eventos ``system/init``, ``assistant``,
``rate_limit_event`` y ``result`` con ``structured_output``. Construye propuestas válidas a
partir de los ids de palabra que encuentra en el contexto.

Modo (variable ``FAKE_CLAUDE_MODE``): ok | unsafe | rate_limit | auth | sleep | invalid |
bad_model. ``FAKE_CLAUDE_LOG`` guarda los argumentos y un resumen de cada llamada.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def arg(name: str) -> str | None:
    argv = sys.argv[1:]
    return argv[argv.index(name) + 1] if name in argv else None


WORD = re.compile(r"(w\d{6})@(\d+\.\d+) (\S+)")


def intervention(words: list[tuple[str, float, str]], k: int, kind: str) -> dict:
    a, b = words[0], words[-1]
    return {
        "anchor_from_word": a[0],
        "anchor_to_word": b[0],
        "start": a[1],
        "end": b[1] + 0.4,
        "segment_ids": [],
        "scene_indices": [0],
        "frame_ids": ["frm_inexistente"] if k == 0 else [],
        "type": kind,
        "goal": f"Objetivo simulado {k}",
        "visual_description": f"Descripción simulada {k}: {' '.join(w[2] for w in words)}",
        "composition": {
            "layout": "overlay_top" if k % 2 == 0 else "overlay_bottom",
            "background": "original_video",
            "region": {"x": 0.05, "y": 0.05 if k % 2 == 0 else 0.75, "w": 0.9, "h": 0.2},
            "notes": "",
        },
        "elements": [
            {
                "kind": "headline",
                "description": "titular",
                "text": words[0][2][:40],
                "role": "primary",
            },
            {"kind": "hud_panel", "description": "panel", "text": None, "role": "secondary"},
        ],
        "motion": {
            "entry": "fade",
            "exit": "fade",
            "easing": "smooth",
            "camera": "none",
            "emphasis": "",
            "entry_seconds": 0.4,
            "exit_seconds": 0.3,
        },
        "transitions": {"into": "cut", "out": "cut"},
        "sfx": [{"kind": "pop", "at": a[1], "description": ""}],
        "intensity": "medium",
        "avoid_face": True,
        "subtitles": "keep",
        "rationale": "Motivo simulado.",
        "evidence": {"observed": ["dato simulado"], "inferred": ["inferencia simulada"]},
        "confidence": "medium",
    }


UNDERSTANDING = {
    "summary": "Resumen simulado.",
    "topic": "tema",
    "intent": "intención",
    "audience": "público",
    "tone": "tono",
    "content_kind": "talking_head",
    "structure": [{"start": 0.0, "end": 1.0, "label": "inicio", "purpose": "abrir"}],
    "scenes": [{"scene_index": 0, "kind": "talking_head", "policy": "open", "observed": "plano"}],
    "observed_facts": ["hecho"],
    "inferences": ["inferencia"],
}
DIRECTION = {
    "concept": "concepto",
    "visual_language": "lenguaje",
    "pacing": "ritmo",
    "typography": "tipografía",
    "color_usage": "color",
    "density": "densidad",
}


def direct(text: str) -> list[dict]:
    """Dirección de animación simulada (Fase 4): ejercita la validación del backend."""
    template = re.search(r"Plantillas disponibles:\n- ([a-z.]+):", text).group(1)
    out = []
    for m in re.finditer(
        r'<transcripcion id="(iv_[a-z0-9]+)">\n(.*?)\n</transcripcion>', text, re.S
    ):
        words = [(w.group(1), w.group(3)) for w in WORD.finditer(m.group(2))]
        if len(words) < 3:
            continue
        (i1, t1), (i2, t2), (_, t3) = words[0], words[1], words[2]
        out.append(
            {
                "id": m.group(1),
                "template": template,
                "title": f"{t1} {t2}",
                "label": None,
                "arrangement": "auto",
                "items": [
                    {"kind": "headline", "text": f"{t1} {t2}", "role": "primary", "cue_word": i1},
                    # Repite parte del anterior: el backend lo fusiona como resaltado.
                    {"kind": "keyword", "text": t2, "cue_word": i2},
                    # Palabra en vez de id: el backend la busca dentro del tramo.
                    {"kind": "label", "text": t3, "cue_word": t3},
                    # Sin contenido legible: se descarta.
                    {"kind": "keyword", "text": "?", "cue_word": "w999999"},
                ],
                "links": [{"source": 0, "target": 1}],
                "custom": [{"type": "rect", "x": 0.6, "y": 0.1, "w": 0.3, "h": 0.1, "fill": True}],
                "rationale": "Dirección simulada.",
            }
        )
    return out


def scene(text: str, words: list[tuple[str, float, str]]) -> dict:
    """Modificación simulada de UNA escena (Fase 5)."""
    data = json.loads(text.split("<escena>\n", 1)[1].split("\n</escena>", 1)[0])
    iv = data["intervencion"]
    instruction = text.split("<instruccion_usuario>\n", 1)[1].split("\n</instruccion_usuario>", 1)[
        0
    ]
    template = re.search(r"Plantillas disponibles:\n- ([a-z.]+):", text).group(1)
    inside = [w for w in words if iv["start"] - 0.3 <= w[1] <= iv["end"]] or words[:3]
    old = data.get("direccion_actual") or {}
    items = [
        {
            "kind": "headline",
            "text": " ".join(w[2] for w in inside[:2])[:40],
            "role": "primary",
            "cue_word": inside[0][0],
        },
        {
            "kind": "label",
            "text": inside[min(2, len(inside) - 1)][2][:40],
            "cue_word": inside[min(2, len(inside) - 1)][0],
        },
        {"kind": "label", "text": inside[-1][2][:40], "cue_word": inside[-1][0]},
    ]
    if "menos texto" in instruction:
        items = items[:1]
    animation = {
        "id": "iv_otro" if "FUERA" in instruction else iv["id"],
        "template": old.get("template") or template,
        "title": items[0]["text"],
        "label": None,
        "arrangement": "auto",
        "text_scale": 1.3 if "grande" in instruction else 1.0,
        "items": items,
        "links": [{"source": 0, "target": 1, "cue_word": inside[-1][0]}] if len(items) > 1 else [],
        "custom": [],
        "rationale": "Escena simulada.",
    }
    intervention = None
    changes = ["Textos y disposición revisados."]
    if any(k in instruction for k in ("diagrama", "movimiento", "más larga")):
        intervention = {
            k: iv[k]
            for k in (
                "anchor_from_word",
                "anchor_to_word",
                "start",
                "end",
                "type",
                "goal",
                "visual_description",
                "composition",
                "elements",
                "motion",
                "transitions",
                "sfx",
                "intensity",
                "avoid_face",
                "subtitles",
                "rationale",
            )
        }
        intervention.update(
            segment_ids=[],
            scene_indices=[],
            frame_ids=[],
            evidence={"observed": [], "inferred": []},
            confidence="medium",
        )
        if "diagrama" in instruction:
            intervention["type"] = "diagram"
            changes.append("La escena pasa a ser un diagrama.")
        if "movimiento" in instruction:
            intervention["intensity"] = "low"
            intervention["motion"] = {**iv["motion"], "easing": "smooth", "entry": "fade"}
            changes.append("Movimiento más contenido.")
        if "más larga" in instruction:
            later = [w for w in words if w[1] > iv["end"] + 1.5]
            if later:
                intervention["anchor_to_word"] = later[0][0]
                intervention["end"] = later[0][1] + 0.3
                changes.append("La escena dura más.")
    return {
        "summary": f"Escena modificada: {instruction[:60]}",
        "changes": changes,
        "intervention": intervention,
        "animation": animation,
    }


def build(schema: dict, text: str) -> dict:
    props = set(schema.get("properties", {}))
    words = [(m.group(1), float(m.group(2)), m.group(3)) for m in WORD.finditer(text)]
    if props == {"ok", "reply"}:
        return {"ok": True, "reply": "listo"}
    if props == {"animations"}:
        return {"animations": direct(text)}
    if props == {"summary", "changes", "intervention", "animation"}:
        return scene(text, words)
    kinds = ["kinetic_typography", "overlay_motion", "diagram", "keep_original"]
    groups = [words[i : i + 3] for i in range(0, len(words), max(3, len(words) // 4))][:4]
    ivs = [intervention(g, k, kinds[k % 4]) for k, g in enumerate(groups) if g]
    if props == {"understanding", "direction", "interventions"}:
        return {"understanding": UNDERSTANDING, "direction": DIRECTION, "interventions": ivs}
    if props == {"understanding", "direction"}:
        return {"understanding": UNDERSTANDING, "direction": DIRECTION}
    if props == {"interventions"}:
        return {"interventions": ivs[:2]}
    # Corrección / alternativa: intervenciones del ámbito en <plan_actual>.
    plan = json.loads(text.split("<plan_actual>\n", 1)[1].split("\n</plan_actual>", 1)[0])
    scope = plan["in_scope"]
    instruction = text.split("<instruccion_usuario>\n", 1)[1].split("\n</instruccion_usuario>", 1)[
        0
    ]
    if "Elimina" in instruction:
        return {"summary": "Eliminada.", "replace": [], "remove": [scope[0]["id"]], "add": []}
    if "FUERA" in instruction and plan["others"]:
        # Intento de tocar una intervención fuera del ámbito (debe ignorarse).
        other = {
            k: v
            for k, v in dict(
                scope[0], id=plan["others"][0]["id"], goal="cambio no permitido"
            ).items()
            if k not in ("status", "user_note")
        }
        changed = {
            k: v
            for k, v in dict(scope[0], goal="Objetivo revisado").items()
            if k not in ("status", "user_note")
        }
        return {
            "summary": "Cambio con intento fuera de ámbito.",
            "replace": [changed, other],
            "remove": [],
            "add": [],
        }
    replaced = []
    for item in scope[:3]:
        new = {k: v for k, v in item.items() if k not in ("status", "user_note")}
        new["goal"] = "Objetivo revisado" if "alternativa" not in text else "Alternativa distinta"
        new["type"] = "diagram" if "diagrama" in instruction else new["type"]
        replaced.append(new)
    return {"summary": "Revisión simulada.", "replace": replaced, "remove": [], "add": []}


def main() -> None:
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
    if sys.argv[1:2] == ["--version"]:
        print("9.9.9 (Claude Code simulado)")
        return
    if sys.argv[1:3] == ["auth", "status"]:
        print(
            json.dumps(
                {
                    "loggedIn": mode != "logged_out",
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                }
            )
        )
        return
    line = sys.stdin.readline()
    msg = json.loads(line)
    blocks = msg["message"]["content"]
    text = "\n".join(b.get("text", "") for b in blocks if b["type"] == "text")
    images = sum(1 for b in blocks if b["type"] == "image")
    schema = json.loads(arg("--json-schema") or "{}")
    log = os.environ.get("FAKE_CLAUDE_LOG")
    if log:
        with open(log, "a") as fh:
            fh.write(
                json.dumps(
                    {
                        "argv": sys.argv[1:],
                        "images": images,
                        "chars": len(text),
                        "env_api_key": "ANTHROPIC_API_KEY" in os.environ,
                        "cwd": os.getcwd(),
                        "schema": sorted(schema.get("properties", {})),
                    }
                )
                + "\n"
            )
    model = arg("--model")
    tools = ["Bash", "Read"] if mode == "unsafe" else ["StructuredOutput"]
    key_source = "ANTHROPIC_API_KEY" if mode == "api_key" else "none"
    if mode != "no_init":
        emit(
            {
                "type": "system",
                "subtype": "init",
                "model": model,
                "tools": tools,
                "mcp_servers": [],
                "apiKeySource": key_source,
                "claude_code_version": "9.9.9",
            }
        )
    if mode == "sleep":
        time.sleep(60)
    emit({"type": "assistant", "message": {"model": model, "content": []}})
    emit(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "overageStatus": "rejected",
                "unifiedWindows": {"five_hour": {"utilization": 0.1, "resetsAt": 2000000000}},
            },
        }
    )
    if mode == "rate_limit":
        emit(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "api_error_status": 429,
                "result": "Claude AI usage limit reached",
            }
        )
        return
    if mode == "auth":
        emit(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "api_error_status": 401,
                "result": "Invalid API key · Please run /login",
            }
        )
        return
    data = None if mode == "invalid" else build(schema, text)
    reported = "claude-sonnet-otro" if mode == "bad_model" else model
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 1234,
            "total_cost_usd": 0.0123,
            "structured_output": data,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 200,
                "cache_creation_input_tokens": 3000,
                "cache_read_input_tokens": 500,
            },
            "modelUsage": {reported: {"inputTokens": 10, "outputTokens": 200}},
        }
    )


if __name__ == "__main__":
    main()
