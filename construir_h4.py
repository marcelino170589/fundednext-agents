# construir_h4.py
"""Convierte velas H1 a H4 agrupando cada 4 velas."""
import argparse
import csv


def construir_h4(input_path, output_path):
    with open(input_path) as f:
        velas_h1 = list(csv.DictReader(f))

    if not velas_h1:
        print(f"❌ {input_path} está vacío")
        return

    velas_h4 = []
    for i in range(0, len(velas_h1), 4):
        grupo = velas_h1[i:i+4]
        if len(grupo) < 4:
            break
        velas_h4.append({
            "time": grupo[0]["time"],
            "open": float(grupo[0]["open"]),
            "high": max(float(v["high"]) for v in grupo),
            "low": min(float(v["low"]) for v in grupo),
            "close": float(grupo[-1]["close"]),
            "volume": sum(float(v.get("volume", 0)) for v in grupo),
        })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(velas_h4)

    print(f"✅ {output_path}: {len(velas_h4)} velas H4 (desde {len(velas_h1)} H1)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    construir_h4(a.input, a.output)
