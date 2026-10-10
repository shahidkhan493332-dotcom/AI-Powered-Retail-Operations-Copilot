"""Explainable category and priority rules for operational triage."""
import re

CATEGORIES = ["POS and Payments", "Inventory and Replenishment", "Pricing and Promotions",
              "Returns and Refunds", "Vendor and Supply Chain", "Product Quality and Safety",
              "Customer Service", "Other or Security"]


def classify(text: str, role: str = "Unknown") -> dict:
    t = text.lower()
    # Highest-risk rules take precedence over routine categories.
    if any(x in t for x in ["ignore previous instructions", "card number", "cvv", "supplier contract", "password", "otp", "full customer database", "hidden prompt"]):
        return result("Other or Security", "P1", 0.99, "Restricted-data or instruction-override request.")
    if any(x in t for x in ["injury", "injured", "recall", "unsafe", "safety concern", "safety risk", "treadmill belt", "equipment malfunction"]):
        return result("Product Quality and Safety", "P1", 0.96, "Potential customer safety, recall, or equipment risk.")
    if any(x in t for x in ["card number", "payment token", "payment data", "cvv", "pin", "otp", "credentials", "password"]):
        return result("Other or Security", "P1", 0.98, "Payment or credential data requires refusal and Security escalation.")
    if any(x in t for x in ["all registers", "store-wide", "cannot process card", "payment outage"]):
        return result("POS and Payments", "P1", 0.96, "Store-wide payment outage requires immediate escalation.")
    if any(x in t for x in ["multiple registers", "several registers", "registers degraded"]):
        return result("POS and Payments", "P2", 0.90, "Multiple registers are degraded and need manager/POS review.")
    if any(x in t for x in ["shelf label", "shelf price", "pos scans", "price mismatch", "promotion", "coupon"]):
        priority = "P2" if any(x in t for x in ["many customers", "multiple customers", "multiple stores", "department"] ) else "P3"
        return result("Pricing and Promotions", priority, 0.88, "Pricing or promotion mismatch reported.")
    if any(x in t for x in ["card reader", "register", "pos", "payment", "receipt printer", "upi terminal", "cash drawer"]):
        return result("POS and Payments", "P3", 0.88, "A register or payment operation is affected.")
    if any(x in t for x in ["return", "refund", "no receipt", "without receipt", "exchange"]):
        amount = _amount(t)
        no_receipt = any(x in t for x in ["without receipt", "no receipt"])
        priority = "P2" if no_receipt or amount >= 5000 else "P3"
        return result("Returns and Refunds", priority, 0.88, "Return request; approval thresholds depend on receipt and value.")
    if any(x in t for x in ["split seam", "split football seam", "quality complaint", "quality complaints", "defective", "cracked", "seam quality"]):
        repeated = any(x in t for x in ["repeated", "multiple", "across stores", "two stores", "complaints"])
        return result("Product Quality and Safety", "P2" if repeated else "P3", 0.86, "Repeated or multi-store quality issues need review." if repeated else "Single product-quality issue needs inspection and documentation.")
    if any(x in t for x in ["short shipment", "vendor", "delivery delayed", "fill rate"]):
        return result("Vendor and Supply Chain", "P2", 0.84, "Supply or receiving issue may affect replenishment.")
    if any(x in t for x in ["stock", "out of stock", "not available", "reorder", "inventory", "academy order"]):
        repeated_or_critical = any(x in t for x in ["out of stock", "not available", "again", "repeated", "academy", "school order", "tournament", "high demand", "false availability"])
        routine_below_reorder = any(x in t for x in ["below reorder point", "below reorder threshold"]) and not any(x in t for x in ["out of stock", "not available", "false availability"])
        priority = "P3" if routine_below_reorder or not repeated_or_critical else "P2"
        return result("Inventory and Replenishment", priority, 0.85, "Routine below-reorder item; still available." if priority == "P3" else "Stock-out or high-impact availability issue reported.")
    if "policy" in t and any(phrase in t for phrase in ["what is", "what's", "explain", "policy question", "how does"]):
        if any(word in t for word in ["pos", "register", "card reader", "payment"]): category = "POS and Payments"
        elif any(word in t for word in ["price", "promotion", "shelf label"]): category = "Pricing and Promotions"
        elif any(word in t for word in ["return", "refund"]): category = "Returns and Refunds"
        elif any(word in t for word in ["inventory", "stock", "reorder"]): category = "Inventory and Replenishment"
        elif any(word in t for word in ["vendor", "shipment", "delivery"]): category = "Vendor and Supply Chain"
        elif any(word in t for word in ["quality", "football seam", "defect"]): category = "Product Quality and Safety"
        else: category = "Other or Security"
        return result(category, "P4", 0.90, "Non-urgent policy guidance request.")
    if any(x in t for x in ["analytics", "unresolved", "dashboard", "incidents from", "how many"]):
        return result("Other or Security", "P4", 0.86, "This is a reporting question over operational records.")
    if any(x in t for x in ["complaint", "upset", "apology", "service recovery"]):
        return result("Customer Service", "P3", 0.72, "Routine customer-service request.")
    return result("Other or Security", "P4", 0.55, "Issue type is unclear; ask for context and escalate if urgent.")


def result(category, priority, confidence, reasoning):
    return {"category": category, "priority": priority, "confidence": confidence, "reasoning": reasoning}


def _amount(text: str) -> int:
    found = re.search(r"(?:inr|rs\.?|₹)\s*([\d,]+)", text, flags=re.I)
    return int(found.group(1).replace(",", "")) if found else 0
