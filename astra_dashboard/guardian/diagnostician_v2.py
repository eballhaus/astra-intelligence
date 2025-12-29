import importlib, json, datetime

class AstraDiagnosticianV2:
    def scan(self):
        report = {"timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), "results": []}
        modules = ["core.guardian.guardian_v7", "engine.data_orchestrator", "learning.funnel.astra_funnel", "ui.dashboard.tab_dashboard_v7"]
        for mod in modules:
            entry = {"module": mod}
            try:
                m = importlib.import_module(mod)
                entry["status"] = "✅ Imported successfully"
                entry["functions"] = [f for f in dir(m) if not f.startswith("_") and callable(getattr(m, f))]
            except Exception as e:
                entry["status"] = "❌ Import failed"
                entry["error"] = str(e)
            report["results"].append(entry)
        try:
            from learning.funnel.astra_funnel import AstraFunnel
            funnel = AstraFunnel()
            out = funnel.run()
            report["results"].append({
                "test": "Funnel.run() output",
                "status": "✅ Valid output" if isinstance(out, list) and len(out) > 0 else "⚠️ Empty or invalid output",
                "details": type(out).__name__
            })
        except Exception as e:
            report["results"].append({"test": "Funnel.run()", "status": "❌ Execution error", "error": str(e)})
        print(json.dumps(report, indent=2))
        return report
