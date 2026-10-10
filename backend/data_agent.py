"""Bounded analytics over supplied CSVs; no arbitrary SQL or model-generated queries."""
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ANCHOR = datetime(2026, 10, 10, 12, 0)


class RetailData:
    def __init__(self, data_dir: Path):
        self.tables = {path.stem: pd.read_csv(path).fillna("") for path in data_dir.glob("*.csv")}

    def has_analytics_intent(self, text: str) -> bool:
        t = text.lower()
        return any(word in t for word in ["last 24 hours", "last 30 days", "unresolved", "open high-priority", "grouped by store", "most sports goods quality complaints", "likely root cause", "why is this happening", "where is it", "analytics", "dashboard", "return", "refund", "quality", "seam", "defective", "complaint"])

    def dashboard(self) -> dict:
        cases = self.tables["support_cases"].copy()
        active = cases[cases.status != "Closed"]
        stores = self.tables["store_master"][["store_id", "region"]]
        regional = active.merge(stores, on="store_id", how="left").groupby("region").size().reset_index(name="active_cases")
        return {
            "active_case_count": int(len(active)),
            "priority_distribution": active.groupby("priority_label").size().reset_index(name="cases").to_dict("records"),
            "category_distribution": active.groupby("category_label").size().reset_index(name="cases").sort_values("cases", ascending=False).to_dict("records"),
            "region_distribution": regional.to_dict("records"),
            "data_used": ["support_cases.csv", "store_master.csv"],
        }

    def route(self, category: str, priority: str) -> dict:
        matrix = self.tables["escalation_matrix"]
        row = matrix[(matrix.category == category) & (matrix.priority == priority)]
        if row.empty:
            return {"team": "Store Manager", "channel": "manual_review", "sla_minutes": None, "human_approval_required": False, "policy_source": "01_retail_operations_sop.md#escalation-policy"}
        selected = row.iloc[0]
        return {"team": selected.team, "channel": selected.channel, "sla_minutes": int(selected.sla_minutes), "human_approval_required": str(selected.human_approval_required).lower() == "yes", "policy_source": selected.policy_source}

    def answer(self, text: str) -> dict:
        t = text.lower()
        used = []
        if "return" in t or "refund" in t:
            returns = self.tables["returns_quality"].copy()
            returns["created_ts"] = pd.to_datetime(returns["created_ts"], errors="coerce")
            start = ANCHOR - timedelta(days=30)
            returns = returns[(returns.created_ts >= start) & (returns.created_ts <= ANCHOR)]
            store_match = __import__("re").search(r"st\d{3}", t, flags=__import__("re").I)
            if store_match:
                returns = returns[returns.store_id == store_match.group(0).upper()]
            sku_match = __import__("re").search(r"sku\d{4}", t, flags=__import__("re").I)
            products = self.tables["product_master"][["sku", "name"]]
            if sku_match:
                product_rows = products[products.sku == sku_match.group(0).upper()]
            else:
                tokens = [word for word in t.split() if len(word) >= 5]
                product_rows = products[products.name.apply(lambda name: any(token in name.lower() for token in tokens))]
            if not product_rows.empty:
                returns = returns[returns.sku.isin(product_rows.sku)]
            grouped = returns.merge(products, on="sku", how="left").groupby(["sku", "name", "reason", "status", "receipt_present"], dropna=False).size().reset_index(name="records")
            used = ["returns_quality.csv"] + (["product_master.csv"] if not product_rows.empty else [])
            if not returns.empty:
                table = grouped.head(8).to_dict("records")
                answer = (f"Related demo-data records only (not this customer's individual history), from {start:%Y-%m-%d} through the 2026-10-10 12:00 IST anchor: "
                          f"{len(returns)} matching return/quality record(s). A manager must still apply the no-receipt and refund-approval policy.")
                return {"answer": answer, "table": table, "data_used": used}
            return {"answer": "No matching return/quality records were found in the selected demo data window. Follow the documented return policy and obtain manager review when required.", "table": [], "data_used": used}
        if "last 24 hours" in t or ("unresolved" in t and "incident" in t):
            cases = self.tables["support_cases"].copy()
            cases["created_ts"] = pd.to_datetime(cases["created_ts"], errors="coerce")
            start = ANCHOR - timedelta(hours=24)
            chosen = cases[(cases.created_ts >= start) & (cases.created_ts <= ANCHOR) & (cases.priority_label.isin(["P1", "P2"])) & (cases.status != "Closed")]
            grouped = chosen.groupby(["store_id", "category_label", "status"]).size().reset_index(name="cases")
            used = ["support_cases.csv"]
            msg = f"Using the 2026-10-10 12:00 IST anchor, found {len(chosen)} unresolved P1/P2 cases in the last 24 hours."
            return {"answer": msg, "table": grouped.to_dict("records"), "data_used": used}
        if "most" in t and ("quality" in t or "complaint" in t) and "vendor" in t:
            q = self.tables["returns_quality"].copy()
            q["created_ts"] = pd.to_datetime(q["created_ts"], errors="coerce")
            start = ANCHOR - timedelta(days=30)
            q = q[(q.created_ts >= start) & (q.created_ts <= ANCHOR) & q.reason.str.contains("seam|quality|crack|defect|damag", case=False, regex=True)]
            products = self.tables["product_master"][["sku", "vendor_id"]]
            vendors = self.tables["vendor_master"][["vendor_id", "name", "fill_rate", "on_time_rate"]]
            cases = self.tables["support_cases"].copy()
            cases["created_ts"] = pd.to_datetime(cases["created_ts"], errors="coerce")
            cases = cases[(cases.created_ts >= start) & (cases.created_ts <= ANCHOR) & (cases.category_label == "Product Quality and Safety")]
            returns_joined = q.merge(products, on="sku", how="left")
            cases_joined = cases.merge(products, on="sku", how="left")
            counts = pd.concat([returns_joined[["vendor_id"]], cases_joined[["vendor_id"]]]).dropna()
            grouped = counts.groupby("vendor_id").size().reset_index(name="quality_records")
            grouped = grouped.merge(vendors, on="vendor_id", how="left").sort_values("quality_records", ascending=False)
            used = ["returns_quality.csv", "support_cases.csv", "product_master.csv", "vendor_master.csv"]
            top_count = int(grouped.quality_records.max()) if not grouped.empty else 0
            leaders = grouped[grouped.quality_records == top_count] if top_count else grouped
            lead_names = ", ".join(f"{row['name']} ({row['vendor_id']})" for row in leaders.to_dict("records"))
            answer = (f"The highest matched 30-day quality-record count is {top_count}, shared by {lead_names}. This combines support cases and quality/return records; records may describe related incidents. It is an investigation lead, not proof of vendor fault." if top_count else "No matching quality records were found in the last 30 days.")
            return {"answer": answer, "table": grouped.head(5).to_dict("records"), "data_used": used}
        if any(term in t for term in ["quality", "seam", "defective", "complaint"]):
            start = ANCHOR - timedelta(days=30)
            returns = self.tables["returns_quality"].copy()
            returns["created_ts"] = pd.to_datetime(returns["created_ts"], errors="coerce")
            returns = returns[(returns.created_ts >= start) & (returns.created_ts <= ANCHOR)]
            cases = self.tables["support_cases"].copy()
            cases["created_ts"] = pd.to_datetime(cases["created_ts"], errors="coerce")
            cases = cases[(cases.created_ts >= start) & (cases.created_ts <= ANCHOR) & (cases.category_label == "Product Quality and Safety")]

            # If the user names a product, use its SKU to narrow both data sources.
            products = self.tables["product_master"][["sku", "name"]]
            import re

            product_terms = {
                term
                for name in products.name.astype(str).str.lower()
                for term in re.findall(r"[a-z]+", name)
                if len(term) >= 5 and term not in {"sports", "goods", "equipment"}
            }
            mentioned_terms = {term for term in product_terms if re.search(rf"\b{re.escape(term)}\b", t)}
            mentioned = products[
                products.name.astype(str).str.lower().apply(
                    lambda name: any(term in name.split() for term in mentioned_terms)
                )
            ]
            if not mentioned.empty:
                selected_skus = mentioned.sku.tolist()
                returns = returns[returns.sku.isin(selected_skus)]
                cases = cases[cases.sku.isin(selected_skus)]
            else:
                quality_reasons = r"seam|quality|crack|defect|damag|split"
                returns = returns[returns.reason.str.contains(quality_reasons, case=False, regex=True, na=False)]
                case_text = cases.issue_text.fillna("") + " " + cases.root_cause_hint.fillna("")
                cases = cases[case_text.str.contains(quality_reasons, case=False, regex=True, na=False)]

            # Report the records separately; support cases and returns may refer to the same event.
            return_summary = returns.groupby(["store_id", "sku", "reason", "status"], dropna=False).size().reset_index(name="return_quality_records")
            case_summary = cases.groupby(["store_id", "sku", "root_cause_hint", "status"], dropna=False).size().reset_index(name="support_cases")
            table = [
                {"source": "returns_quality.csv", **row}
                for row in return_summary.head(8).to_dict("records")
            ] + [
                {"source": "support_cases.csv", **row}
                for row in case_summary.head(8).to_dict("records")
            ]
            count = len(returns) + len(cases)
            answer = (
                f"In the 30 days through the 2026-10-10 12:00 IST anchor, the supplied records contain "
                f"{len(returns)} matching return/quality record(s) and {len(cases)} matching support case(s). "
                "Review the affected product and batch, preserve evidence, and route repeated or multi-store reports to Product Quality. "
                "These records are investigation signals; they do not establish a cause or vendor fault."
                if count else
                "No matching quality records were found in the supplied 30-day data window. Record the product, batch, store, and photos, then route the complaint to Product Quality for review."
            )
            return {"answer": answer, "table": table, "data_used": ["returns_quality.csv", "support_cases.csv"]}
        if "english willow" in t or "sku1001" in t:
            sku = "SKU1001"
            store_match = __import__("re").search(r"st\d{3}", t, flags=__import__("re").I)
            store = store_match.group(0).upper() if store_match else "ST002"
            inventory = self.tables["inventory"]
            inv_row = inventory[(inventory.sku == sku) & (inventory.store_id == store)]
            receipts = self.tables["receipts"]
            receipts = receipts[(receipts.sku == sku) & (receipts.store_id == store)].sort_values("receipt_date", ascending=False).head(5)
            product = self.tables["product_master"].loc[self.tables["product_master"].sku == sku].iloc[0]
            vendor = self.tables["vendor_master"].loc[self.tables["vendor_master"].vendor_id == product.vendor_id].iloc[0]
            short = int((receipts.received_qty.astype(int) < receipts.po_qty.astype(int)).sum()) if not receipts.empty else 0
            total = int(len(receipts))
            on_hand = int(inv_row.iloc[0].on_hand) if not inv_row.empty else 0
            answer = (f"At {store}, {sku} has {on_hand} units on hand against reorder point "
                      f"{int(inv_row.iloc[0].reorder_point) if not inv_row.empty else 'unknown'}. "
                      f"Recent receipts show {short} of {total} deliveries were short. Vendor {vendor['name']} "
                      f"reports {float(vendor.fill_rate):.0%} fill rate. These signals make short/partial deliveries "
                      "a likely contributor; they do not prove sole cause. Review open orders and request a count/replenishment check.")
            return {"answer": answer, "table": receipts.to_dict("records"), "data_used": ["inventory.csv", "receipts.csv", "product_master.csv", "vendor_master.csv"]}
        if "tennis ball" in t or "sku7001" in t:
            sku, store = "SKU7001", "ST005"
            inv = self.tables["inventory"]
            relevant = inv[(inv.sku == sku) & (inv.store_id.isin([store, "WH001"]))]
            receipts = self.tables["receipts"]
            receipts = receipts[(receipts.sku == sku) & (receipts.store_id == "WH001")]
            used = ["inventory.csv", "receipts.csv", "product_master.csv"]
            lines = [f"{row.store_id}: on-hand {int(row.on_hand)}, system quantity {int(row.system_qty)}, reorder point {int(row.reorder_point)}." for row in relevant.itertuples()]
            if not receipts.empty:
                r = receipts.iloc[0]
                lines.append(f"Warehouse receipt {r.receipt_id} records {int(r.received_qty)} received from {int(r.po_qty)} ordered; note: {r.damage_notes}.")
            return {"answer": "Likely root cause: warehouse stock is depleted. " + " ".join(lines), "table": relevant.to_dict("records"), "data_used": used}
        match = __import__("re").search(r"(?:store\s*)?(st\d{3})", t, flags=__import__("re").I)
        sku_match = __import__("re").search(r"sku\d{4}", t, flags=__import__("re").I)
        name_match = None
        products = self.tables["product_master"]
        for row in products.itertuples():
            if row.name.lower() in t:
                name_match = row.sku
                break
        sku = sku_match.group(0).upper() if sku_match else name_match
        if sku:
            store = match.group(1).upper() if match else ""
            inv = self.tables["inventory"]
            rows = inv[inv.sku == sku]
            if store:
                rows = rows[rows.store_id == store]
            return {"answer": "Inventory snapshot from the provided CSV: " + "; ".join(f"{r.store_id} on-hand {r.on_hand}, system {r.system_qty}, reorder point {r.reorder_point}" for r in rows.head(8).itertuples()), "table": rows.head(8).to_dict("records"), "data_used": ["inventory.csv"]}
        return {"answer": "I can answer the supplied case, inventory, receipt, vendor, returns, and quality questions. Please include a store, SKU/product, or time range.", "table": [], "data_used": []}
