# journal_pdf.py
"""Genera PDF de auditoría por señal."""
import os
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import journal


def generar_pdf(signal_id: int, output: str = None):
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Heading1"], fontSize=16,
                            textColor=colors.HexColor("#1a5276"))
    h = ParagraphStyle("h", parent=styles["Heading2"], fontSize=12,
                        textColor=colors.HexColor("#2874a6"))

    with journal.get_db() as conn:
        sig = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        if not sig:
            print(f"Señal {signal_id} no encontrada")
            return
        sig = dict(sig)
        checks = [dict(r) for r in conn.execute(
            "SELECT * FROM rule_checks WHERE signal_id=?", (signal_id,))]
        dec = dict(conn.execute("SELECT * FROM decisions WHERE id=?",
                                 (sig["decision_id"],)).fetchone() or {})

    output = output or f"data/reports/signal_{signal_id}.pdf"
    os.makedirs(os.path.dirname(output), exist_ok=True)

    doc = SimpleDocTemplate(output, pagesize=A4)
    story = []
    story.append(Paragraph(f"Reporte FNL:004 — Señal #{signal_id}", title))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Generado: {date.today()}", styles["Normal"]))
    story.append(Spacer(1, 20))

    story.append(Paragraph("Datos de la operación", h))
    data = [["Campo", "Valor"],
            ["Timestamp", sig["ts"][:19]],
            ["Par", sig["symbol"]],
            ["Dirección", sig["direction"]],
            ["Entrada", str(sig["entry"])],
            ["SL", str(sig["sl"])],
            ["TP", str(sig["tp"])],
            ["Lotaje", str(sig["lotage"])],
            ["Score consenso", str(sig["score"])],
            ["Divergencia", str(sig["divergence"])]]
    t = Table(data, colWidths=[120, 300])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2874a6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
    story.append(t)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Decisión del orquestador", h))
    dec_data = [["Campo", "Valor"],
                ["Operar", "SÍ" if dec.get("operar") else "NO"],
                ["Motivo", dec.get("motivo", "—")],
                ["Capa", str(dec.get("capa", "—"))]]
    t2 = Table(dec_data, colWidths=[120, 300])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2874a6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
    story.append(t2)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Validación FNL:004", h))
    cdata = [["Check", "Resultado", "Valor", "Límite"]]
    for c in checks:
        cdata.append([c["check_name"], "✓" if c["passed"] else "✗",
                       str(c["value"]), str(c["limit_value"])])
    if len(cdata) == 1:
        cdata.append(["Sin checks", "", "", ""])
    t3 = Table(cdata, colWidths=[120, 80, 100, 100])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2874a6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
    story.append(t3)

    doc.build(story)
    print(f"✓ PDF: {output}")


if __name__ == "__main__":
    import sys
    generar_pdf(int(sys.argv[1]) if len(sys.argv) > 1 else 1)