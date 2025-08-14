from flask import jsonify, send_file
import io
import pandas as pd

def json_response(data):
    """Devuelve una respuesta JSON para Flask."""
    return jsonify(data)

def excel_response(data, filename="resultados.xlsx"):
    """
    Genera un archivo Excel en memoria y lo devuelve con send_file.
    """
    output = io.BytesIO()
    df = pd.DataFrame(data)
    df.to_excel(output, index=False)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )