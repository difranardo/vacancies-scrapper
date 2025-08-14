from typing import Any, Dict

def worker_scrape(scraper_class, **kwargs) -> Dict[str, Any]:
    """
    Ejecuta un scraper y devuelve sus resultados como diccionario.
    Lógica de orquestación, no depende de la infraestructura.
    """
    scraper = scraper_class(**kwargs)
    data = scraper.run()
    return {
        "status": "ok",
        "count": len(data) if data else 0,
        "results": data
    }