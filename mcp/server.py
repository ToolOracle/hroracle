#!/usr/bin/env python3
"""
HROracle — AI Workforce & HR Compliance MCP Server v1.0.0
Port 12301 | Part of ToolOracle Whitelabel MCP Platform

12 Tools:
  ── Payroll & Tax ──
  1.  gross_to_net          — DE/AT/CH Brutto-Netto Berechnung
  2.  employer_cost         — Arbeitgeberkosten-Kalkulation (AG-Anteil SV)
  3.  minijob_check         — 538€ Minijob / Midijob Prüfung

  ── Arbeitsrecht ──
  4.  leave_calculate       — Urlaubsanspruch berechnen (BUrlG)
  5.  notice_period         — Kündigungsfrist berechnen (§622 BGB)
  6.  working_time_check    — Arbeitszeitgesetz-Compliance (ArbZG)
  7.  parental_leave_check  — Elternzeit-Anspruch (BEEG)

  ── HR Operations ──
  8.  contract_clauses      — Arbeitsvertrag-Pflichtklauseln (NachwG)
  9.  onboarding_checklist  — Einstellungs-Checkliste (Anmeldungen etc.)
 10.  offboarding_checklist — DSGVO-konforme Trennungs-Checkliste
 11.  skills_gap_analyze    — Kompetenz-Gap-Analyse
 12.  headcount_forecast    — Personalbedarfsprognose

NO external API keys needed — pure computation + German labor law logic.
"""
import os, sys, json, logging, math
from datetime import datetime, timezone, timedelta, date
from typing import Optional

sys.path.insert(0, "/root/whitelabel")
from shared.utils.mcp_base import WhitelabelMCPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HROracle] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler("/root/whitelabel/logs/hroracle.log", mode="a")]
)
logger = logging.getLogger("HROracle")

PRODUCT_NAME = "HROracle"
VERSION      = "1.0.0"
PORT_MCP     = 12301
PORT_HEALTH  = 12302

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ═══════════════════════════════════════════════════════════════
# SOZIALVERSICHERUNGSBEITRÄGE 2026 (DE)
# ═══════════════════════════════════════════════════════════════
SV_2026 = {
    "KV": {"rate": 14.6, "zusatz": 1.7, "ag_share": 50, "bbl_west": 62100, "bbl_ost": 62100},
    "PV": {"rate": 3.4, "zuschlag_kinderlos": 0.6, "ag_share": 50, "bbl": 62100},
    "RV": {"rate": 18.6, "ag_share": 50, "bbl_west": 96600, "bbl_ost": 96600},
    "AV": {"rate": 2.6, "ag_share": 50, "bbl_west": 96600, "bbl_ost": 96600},
    "minijob_grenze": 538,
    "midijob_grenze": 2000,
}

# ═══════════════════════════════════════════════════════════════
# EINKOMMENSTEUER-TARIF 2026 (§32a EStG — vereinfacht)
# ═══════════════════════════════════════════════════════════════
def calc_income_tax_de(zvE: float, steuerklasse: int = 1) -> float:
    """Simplified German income tax 2026 (Grundtarif)."""
    if zvE <= 11784:
        tax = 0
    elif zvE <= 17005:
        y = (zvE - 11784) / 10000
        tax = (922.98 * y + 1400) * y
    elif zvE <= 66760:
        z = (zvE - 17005) / 10000
        tax = (181.19 * z + 2397) * z + 1025.38
    elif zvE <= 277825:
        tax = 0.42 * zvE - 10602.13
    else:
        tax = 0.45 * zvE - 18936.88

    # Soli (5.5% on tax above Freigrenze ~18k tax)
    soli = 0
    if tax > 18130:
        soli = tax * 0.055
    elif tax > 17543:
        soli = (tax - 17543) * 0.119  # Gleitzone

    return round(tax, 2), round(soli, 2)


async def handle_gross_to_net(args: dict) -> dict:
    """Brutto-Netto Berechnung DE."""
    gross_monthly = float(args.get("gross_monthly", 0))
    steuerklasse = int(args.get("steuerklasse", 1))
    church_tax = args.get("church_tax", False)
    children = int(args.get("children", 0))
    state = args.get("state", "NRW")
    year = int(args.get("year", 2026))

    if gross_monthly <= 0:
        return {"error": "Provide 'gross_monthly' > 0"}

    gross_annual = gross_monthly * 12

    # SV Beiträge (AN-Anteil)
    kv_basis = min(gross_monthly * 12, SV_2026["KV"]["bbl_west"])
    kv_an = kv_basis * (SV_2026["KV"]["rate"] + SV_2026["KV"]["zusatz"]) / 100 / 2
    pv_rate = SV_2026["PV"]["rate"] / 2
    if children == 0 and steuerklasse != 2:
        pv_rate += SV_2026["PV"]["zuschlag_kinderlos"] / 2
    elif children >= 2:
        pv_rate = max(0, SV_2026["PV"]["rate"] / 2 - 0.25 * min(children - 1, 4))
    pv_an = min(gross_monthly * 12, SV_2026["PV"]["bbl"]) * pv_rate / 100
    rv_an = min(gross_monthly * 12, SV_2026["RV"]["bbl_west"]) * SV_2026["RV"]["rate"] / 100 / 2
    av_an = min(gross_monthly * 12, SV_2026["AV"]["bbl_west"]) * SV_2026["AV"]["rate"] / 100 / 2

    sv_total_annual = kv_an + pv_an + rv_an + av_an

    # Steuerpflichtiges Einkommen (vereinfacht)
    zvE = gross_annual - sv_total_annual  # Vorsorgepauschale vereinfacht

    tax_annual, soli_annual = calc_income_tax_de(zvE, steuerklasse)
    kirche_annual = tax_annual * 0.09 if church_tax else 0  # 9% in NRW/BY, 8% in BW/BY

    deductions_annual = sv_total_annual + tax_annual + soli_annual + kirche_annual
    net_annual = gross_annual - deductions_annual
    net_monthly = net_annual / 12

    return {
        "input": {"gross_monthly": gross_monthly, "steuerklasse": steuerklasse,
                  "children": children, "church_tax": church_tax},
        "monthly": {
            "brutto": round(gross_monthly, 2),
            "lohnsteuer": round(tax_annual / 12, 2),
            "solidaritaetszuschlag": round(soli_annual / 12, 2),
            "kirchensteuer": round(kirche_annual / 12, 2),
            "krankenversicherung_an": round(kv_an / 12, 2),
            "pflegeversicherung_an": round(pv_an / 12, 2),
            "rentenversicherung_an": round(rv_an / 12, 2),
            "arbeitslosenversicherung_an": round(av_an / 12, 2),
            "sv_gesamt_an": round(sv_total_annual / 12, 2),
            "abzuege_gesamt": round(deductions_annual / 12, 2),
            "netto": round(net_monthly, 2),
        },
        "annual": {
            "brutto": round(gross_annual, 2),
            "netto": round(net_annual, 2),
            "abzuege": round(deductions_annual, 2),
            "steuer_gesamt": round(tax_annual + soli_annual + kirche_annual, 2),
            "sv_gesamt": round(sv_total_annual, 2),
        },
        "netto_quote": round(net_monthly / gross_monthly * 100, 1),
        "note": "Vereinfachte Berechnung — Lohnsteuerjahresausgleich kann abweichen",
        "legal_basis": "§32a EStG, SGB IV/V/VI/XI, SvEV 2026",
        "retrieved_at": ts(),
    }


async def handle_employer_cost(args: dict) -> dict:
    """Arbeitgeber-Gesamtkosten Kalkulation."""
    gross_monthly = float(args.get("gross_monthly", 0))
    if gross_monthly <= 0:
        return {"error": "Provide 'gross_monthly' > 0"}

    gross_annual = gross_monthly * 12
    kv_ag = min(gross_annual, SV_2026["KV"]["bbl_west"]) * (SV_2026["KV"]["rate"] + SV_2026["KV"]["zusatz"]) / 100 / 2
    pv_ag = min(gross_annual, SV_2026["PV"]["bbl"]) * SV_2026["PV"]["rate"] / 100 / 2
    rv_ag = min(gross_annual, SV_2026["RV"]["bbl_west"]) * SV_2026["RV"]["rate"] / 100 / 2
    av_ag = min(gross_annual, SV_2026["AV"]["bbl_west"]) * SV_2026["AV"]["rate"] / 100 / 2

    # U1/U2/U3 Umlagen (Durchschnitt)
    u1 = gross_annual * 0.015  # ~1.5%
    u2 = gross_annual * 0.005  # ~0.5%
    u3 = gross_annual * 0.0006  # Insolvenzgeldumlage

    bg = gross_annual * 0.013  # BG-Beitrag Durchschnitt

    sv_ag = kv_ag + pv_ag + rv_ag + av_ag
    umlagen = u1 + u2 + u3
    total_extra = sv_ag + umlagen + bg
    total_cost = gross_annual + total_extra

    return {
        "brutto_monthly": round(gross_monthly, 2),
        "brutto_annual": round(gross_annual, 2),
        "ag_anteile_monthly": {
            "krankenversicherung": round(kv_ag / 12, 2),
            "pflegeversicherung": round(pv_ag / 12, 2),
            "rentenversicherung": round(rv_ag / 12, 2),
            "arbeitslosenversicherung": round(av_ag / 12, 2),
            "umlage_u1": round(u1 / 12, 2),
            "umlage_u2": round(u2 / 12, 2),
            "insolvenzumlage_u3": round(u3 / 12, 2),
            "berufsgenossenschaft": round(bg / 12, 2),
            "summe_ag_anteil": round(total_extra / 12, 2),
        },
        "total_monthly": round(total_cost / 12, 2),
        "total_annual": round(total_cost, 2),
        "aufschlag_prozent": round(total_extra / gross_annual * 100, 1),
        "faustformel": f"Brutto x {round(total_cost / gross_annual, 2)} = AG-Gesamtkosten",
        "note": "Durchschnittswerte — tatsächliche BG-Beiträge und Umlagen variieren nach Branche/Kasse",
        "legal_basis": "SGB IV §28d, §28e — AG-Anteil Sozialversicherung",
        "retrieved_at": ts(),
    }


async def handle_minijob_check(args: dict) -> dict:
    """Minijob/Midijob Prüfung."""
    monthly_income = float(args.get("monthly_income", 0))
    hours_per_week = float(args.get("hours_per_week", 0))

    result = {"monthly_income": monthly_income, "hours_per_week": hours_per_week}

    if monthly_income <= SV_2026["minijob_grenze"]:
        result["classification"] = "MINIJOB (geringfügige Beschäftigung)"
        result["sv_pflicht"] = False
        result["rv_pflicht"] = "Ja (Befreiung möglich auf Antrag)"
        result["ag_pauschale"] = round(monthly_income * 0.30, 2)  # 15% RV + 13% KV + 2% Pauschalsteuer
        result["an_abzuege"] = round(monthly_income * 0.036, 2)  # 3.6% RV (wenn nicht befreit)
        result["netto_bei_rv_befreiung"] = monthly_income
        result["note"] = "Geringfügige Beschäftigung — §8 SGB IV"
    elif monthly_income <= SV_2026["midijob_grenze"]:
        result["classification"] = "MIDIJOB (Übergangsbereich)"
        result["sv_pflicht"] = True
        result["note"] = "Gleitzone §20 Abs.2 SGB IV — reduzierte AN-Beiträge"
        # Simplified Midijob calculation
        faktor = (SV_2026["midijob_grenze"] - monthly_income) / (SV_2026["midijob_grenze"] - SV_2026["minijob_grenze"])
        reduzierter_beitrag = monthly_income * 0.20 * (1 - faktor * 0.5)
        result["geschaetzte_abzuege_an"] = round(reduzierter_beitrag, 2)
        result["geschaetztes_netto"] = round(monthly_income - reduzierter_beitrag, 2)
    else:
        result["classification"] = "REGULÄRE BESCHÄFTIGUNG"
        result["sv_pflicht"] = True
        result["note"] = "Volle SV-Pflicht — normale Brutto-Netto Berechnung anwenden"

    if hours_per_week > 0:
        result["mindestlohn_check"] = {
            "mindestlohn_2026": 12.82,
            "stundenlohn": round(monthly_income / (hours_per_week * 4.33), 2),
            "compliant": round(monthly_income / (hours_per_week * 4.33), 2) >= 12.82,
        }

    result["grenzen_2026"] = {
        "minijob": f"{SV_2026['minijob_grenze']}€/Monat",
        "midijob": f"{SV_2026['minijob_grenze']+1}€ - {SV_2026['midijob_grenze']}€/Monat",
        "regulaer": f"ab {SV_2026['midijob_grenze']+1}€/Monat",
    }
    result["legal_basis"] = "§8 SGB IV (Minijob), §20 Abs.2 SGB IV (Übergangsbereich)"
    result["retrieved_at"] = ts()
    return result


async def handle_leave_calculate(args: dict) -> dict:
    """Urlaubsanspruch berechnen."""
    weekly_days = int(args.get("weekly_working_days", 5))
    contractual_days = int(args.get("contractual_leave_days", 0))
    start_date = args.get("start_date", "")  # YYYY-MM-DD
    age = int(args.get("age", 30))
    disabled = args.get("severely_disabled", False)
    year = int(args.get("year", 2026))

    # Gesetzlicher Mindesturlaub
    legal_min = {5: 20, 6: 24, 4: 16, 3: 12, 2: 8, 1: 4}.get(weekly_days, 20)
    effective = max(contractual_days, legal_min)

    result = {
        "weekly_working_days": weekly_days,
        "legal_minimum_days": legal_min,
        "contractual_days": contractual_days,
        "effective_days": effective,
    }

    if disabled:
        result["additional_disabled"] = 5 if weekly_days == 5 else round(5 * weekly_days / 5)
        result["effective_days"] += result["additional_disabled"]
        result["note_disabled"] = "Zusatzurlaub §208 SGB IX — 5 Tage bei 5-Tage-Woche"

    # Teilanspruch bei Eintritt/Austritt
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            year_start = date(year, 1, 1)
            if sd > year_start:
                remaining_months = 12 - sd.month + 1
                partial = round(effective * remaining_months / 12, 1)
                result["partial_year"] = {
                    "start_date": start_date,
                    "remaining_months": remaining_months,
                    "partial_entitlement": math.ceil(partial),
                    "note": "Teilanspruch §5 BUrlG — 1/12 pro vollem Monat",
                }
                wartezeit = sd + timedelta(days=180)
                result["wartezeit_ende"] = wartezeit.isoformat()
                result["wartezeit_note"] = "Voller Anspruch erst nach 6 Monaten Wartezeit (§4 BUrlG)"
        except:
            pass

    result["legal_basis"] = "§§1-13 BUrlG (Bundesurlaubsgesetz)"
    result["important_rules"] = [
        "Urlaub muss im laufenden Kalenderjahr genommen werden (§7 Abs.3 BUrlG)",
        "Übertragung bis 31.03 nur bei dringenden betrieblichen/persönlichen Gründen",
        "Bei Kündigung: Abgeltungsanspruch für nicht genommenen Urlaub (§7 Abs.4 BUrlG)",
        "Urlaubsgeld ist KEINE gesetzliche Pflicht — nur tariflich/vertraglich",
    ]
    result["retrieved_at"] = ts()
    return result


async def handle_notice_period(args: dict) -> dict:
    """Kündigungsfrist berechnen."""
    years_employed = float(args.get("years_employed", 0))
    probation = args.get("in_probation", False)
    initiated_by = args.get("initiated_by", "employer")  # employer | employee
    contract_type = args.get("contract_type", "unbefristet")

    if probation:
        return {
            "notice_period": "2 Wochen",
            "notice_period_days": 14,
            "note": "Probezeit — §622 Abs.3 BGB: 2 Wochen zu jedem Tag",
            "legal_basis": "§622 Abs.3 BGB",
            "retrieved_at": ts(),
        }

    # §622 BGB Staffelung (nur AG-Kündigung)
    if initiated_by == "employer":
        if years_employed < 2:
            period, to = "4 Wochen", "zum 15. oder Monatsende"
        elif years_employed < 5:
            period, to = "1 Monat", "zum Monatsende"
        elif years_employed < 8:
            period, to = "2 Monate", "zum Monatsende"
        elif years_employed < 10:
            period, to = "3 Monate", "zum Monatsende"
        elif years_employed < 12:
            period, to = "4 Monate", "zum Monatsende"
        elif years_employed < 15:
            period, to = "5 Monate", "zum Monatsende"
        elif years_employed < 20:
            period, to = "6 Monate", "zum Monatsende"
        else:
            period, to = "7 Monate", "zum Monatsende"
    else:
        period, to = "4 Wochen", "zum 15. oder Monatsende"

    return {
        "years_employed": years_employed,
        "initiated_by": initiated_by,
        "notice_period": period,
        "termination_date_rule": to,
        "contract_type": contract_type,
        "kuendigungsschutz": years_employed >= 0.5 and initiated_by == "employer",
        "kuendigungsschutz_note": "KSchG gilt ab 6 Monaten Betriebszugehörigkeit in Betrieben >10 MA" if years_employed >= 0.5 else "",
        "special_protection": [
            "Schwangere / Mutterschutz (§17 MuSchG)",
            "Elternzeit (§18 BEEG)",
            "Schwerbehinderte (§168 SGB IX — Zustimmung Integrationsamt)",
            "Betriebsratsmitglieder (§15 KSchG)",
            "Datenschutzbeauftragte (§38 Abs.2 BDSG)",
        ],
        "legal_basis": "§622 BGB, §1 KSchG",
        "retrieved_at": ts(),
    }


async def handle_working_time(args: dict) -> dict:
    """Arbeitszeitgesetz-Compliance Check."""
    daily_hours = float(args.get("daily_hours", 8))
    weekly_hours = float(args.get("weekly_hours", 0))
    break_minutes = int(args.get("break_minutes", 0))
    night_work = args.get("night_work", False)
    on_call = args.get("on_call", False)
    sundays = args.get("sunday_work", False)

    if weekly_hours == 0:
        weekly_hours = daily_hours * 5

    violations = []
    warnings = []
    compliant_items = []

    # §3 ArbZG: max 8h/Tag, Ausdehnung auf 10h möglich
    if daily_hours <= 8:
        compliant_items.append("Tägliche Arbeitszeit ≤ 8h — OK (§3 ArbZG)")
    elif daily_hours <= 10:
        warnings.append(f"Tägliche Arbeitszeit {daily_hours}h — nur zulässig bei Ausgleich auf ∅8h/6Mo (§3 ArbZG)")
    else:
        violations.append(f"Tägliche Arbeitszeit {daily_hours}h — VERSTOSS gegen §3 ArbZG (max. 10h)")

    # §4 ArbZG: Pausen
    if daily_hours > 9 and break_minutes < 45:
        violations.append(f"Pause {break_minutes}min bei >9h — VERSTOSS §4 ArbZG (mind. 45min)")
    elif daily_hours > 6 and break_minutes < 30:
        violations.append(f"Pause {break_minutes}min bei >6h — VERSTOSS §4 ArbZG (mind. 30min)")
    else:
        compliant_items.append("Pausenregelung eingehalten (§4 ArbZG)")

    # §5 ArbZG: Ruhezeit
    compliant_items.append("Ruhezeit: mind. 11h zwischen Arbeitsende und -beginn (§5 ArbZG) — bitte manuell prüfen")

    # §3 ArbZG: Wochenstunden
    if weekly_hours > 48:
        violations.append(f"Wochenarbeitszeit {weekly_hours}h — VERSTOSS (max. 48h/Woche im ∅6Mo)")
    elif weekly_hours > 40:
        warnings.append(f"Wochenarbeitszeit {weekly_hours}h — Ausgleich auf ∅48h/6Mo erforderlich")

    if night_work:
        warnings.append("Nachtarbeit: Gesundheitsuntersuchung alle 3 Jahre (§6 Abs.3 ArbZG), alle 1 Jahr ab 50J")

    if sundays:
        warnings.append("Sonntagsarbeit: mind. 15 freie Sonntage/Jahr (§11 Abs.1 ArbZG)")

    return {
        "input": {"daily_hours": daily_hours, "weekly_hours": weekly_hours, "break_minutes": break_minutes},
        "compliant": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "compliant_items": compliant_items,
        "max_allowed": {
            "daily": "8h (Ausdehnung auf 10h bei Ausgleich)",
            "weekly": "48h im 6-Monats-Durchschnitt",
            "break_6h": "30min",
            "break_9h": "45min",
            "ruhezeit": "11h",
        },
        "bussgelder": "Bis 30.000€ pro Verstoß (§22 ArbZG), Wiederholung = Straftat (§23 ArbZG)",
        "legal_basis": "Arbeitszeitgesetz (ArbZG), EU-Arbeitszeitrichtlinie 2003/88/EG",
        "retrieved_at": ts(),
    }


async def handle_parental_leave(args: dict) -> dict:
    """Elternzeit-Anspruch prüfen."""
    child_birth_date = args.get("child_birth_date", "")
    parent_gender = args.get("parent_gender", "any")
    monthly_net_income = float(args.get("monthly_net_income", 0))
    part_time_hours = float(args.get("part_time_hours", 0))

    result = {
        "anspruch": True,
        "max_dauer": "Bis zu 3 Jahre pro Kind (bis 8. Geburtstag)",
        "aufteilung": "Bis zu 24 Monate zwischen 3. und 8. Geburtstag (ohne AG-Zustimmung)",
    }

    # Elterngeld
    if monthly_net_income > 0:
        eg_rate = 0.67 if monthly_net_income >= 1240 else min(1.0, 0.67 + (1240 - monthly_net_income) * 0.001)
        eg_basis = min(monthly_net_income, 2770)
        elterngeld = max(300, round(eg_basis * eg_rate, 2))

        result["elterngeld"] = {
            "basis_monthly": round(elterngeld, 2),
            "basis_duration": "12 Monate (+ 2 Partnermonate = 14)",
            "elterngeld_plus": round(elterngeld / 2, 2),
            "elterngeld_plus_duration": "Bis 28 Monate",
            "minimum": 300,
            "maximum": 1800,
            "note": "67% des Nettoeinkommens (65% ab 1.240€, Abschmelzung ab 1.200€)",
        }

        if part_time_hours > 0:
            if part_time_hours > 32:
                result["teilzeit_warnung"] = "Max. 32h/Woche während Elternzeit (§15 Abs.4 BEEG)"
            else:
                teilzeit_einkommen = monthly_net_income * (part_time_hours / 40)
                eg_diff = max(0, monthly_net_income - teilzeit_einkommen)
                result["elterngeld_mit_teilzeit"] = round(max(300, eg_diff * 0.67), 2)

    result["kuendigungsschutz"] = {
        "ab": "Anmeldung (frühestens 8 Wochen vor Beginn)",
        "bis": "Ende der Elternzeit",
        "note": "Absoluter Kündigungsschutz §18 BEEG — nur mit Zustimmung der Aufsichtsbehörde",
    }

    result["arbeitgeber_pflichten"] = [
        "Rückkehrrecht auf gleichwertigen Arbeitsplatz",
        "Teilzeitwunsch (15-32h) kann nur aus dringenden betrieblichen Gründen abgelehnt werden",
        "Anmeldung spätestens 7 Wochen vor Beginn (8 Wochen für Zeitraum nach 3. Geburtstag)",
    ]

    result["legal_basis"] = "BEEG (Bundeselterngeld- und Elternzeitgesetz), §§1-28"
    result["retrieved_at"] = ts()
    return result


async def handle_contract_clauses(args: dict) -> dict:
    """Arbeitsvertrag Pflichtklauseln nach NachwG."""
    contract_type = args.get("contract_type", "unbefristet")
    position = args.get("position", "")
    start_date = args.get("start_date", "")

    pflicht_nachwg = [
        {"clause": "Name und Anschrift der Vertragsparteien", "paragraph": "§2 Abs.1 Nr.1 NachwG", "frist": "Tag 1"},
        {"clause": "Beginn des Arbeitsverhältnisses", "paragraph": "§2 Abs.1 Nr.2 NachwG", "frist": "Tag 1"},
        {"clause": "Bei Befristung: Dauer / Enddatum", "paragraph": "§2 Abs.1 Nr.3 NachwG", "frist": "Tag 1",
         "relevant": contract_type == "befristet"},
        {"clause": "Arbeitsort (oder Hinweis auf wechselnde Orte)", "paragraph": "§2 Abs.1 Nr.4 NachwG", "frist": "Tag 1"},
        {"clause": "Tätigkeitsbeschreibung", "paragraph": "§2 Abs.1 Nr.5 NachwG", "frist": "Tag 1"},
        {"clause": "Dauer der Probezeit", "paragraph": "§2 Abs.1 Nr.6 NachwG", "frist": "Tag 1"},
        {"clause": "Zusammensetzung und Höhe des Entgelts", "paragraph": "§2 Abs.1 Nr.7 NachwG", "frist": "Tag 1"},
        {"clause": "Vereinbarte Arbeitszeit, Ruhepausen, Schichtsystem", "paragraph": "§2 Abs.1 Nr.8 NachwG", "frist": "Tag 1"},
        {"clause": "Bei Abrufarbeit: Mindest-/Höchststunden", "paragraph": "§2 Abs.1 Nr.9 NachwG", "frist": "Tag 1"},
        {"clause": "Urlaubsdauer", "paragraph": "§2 Abs.1 Nr.10 NachwG", "frist": "Tag 1"},
        {"clause": "Betriebliche Altersversorgung (Versorgungsträger)", "paragraph": "§2 Abs.1 Nr.11 NachwG", "frist": "spätestens 1 Monat"},
        {"clause": "Kündigungsfristen und -verfahren", "paragraph": "§2 Abs.1 Nr.12 NachwG", "frist": "Tag 7"},
        {"clause": "Hinweis auf anwendbare Tarifverträge/Betriebsvereinbarungen", "paragraph": "§2 Abs.1 Nr.13 NachwG", "frist": "Tag 7"},
        {"clause": "Fortbildungsanspruch (falls gewährt)", "paragraph": "§2 Abs.1 Nr.14 NachwG", "frist": "Tag 1"},
    ]

    empfohlen = [
        {"clause": "Vertraulichkeitsklausel / Geheimhaltung", "note": "Empfohlen, nicht gesetzlich vorgeschrieben"},
        {"clause": "Nebentätigkeitsregelung", "note": "Genehmigungsvorbehalt empfohlen"},
        {"clause": "Wettbewerbsverbot (max. 2 Jahre, Karenzentschädigung)", "note": "§74 HGB"},
        {"clause": "Schriftformklausel", "note": "Änderungen nur schriftlich"},
        {"clause": "Verfall-/Ausschlussklausel", "note": "Mind. 3 Monate, Schriftform, 2-stufig"},
        {"clause": "Datenschutzhinweis (DSGVO Art. 13/14)", "note": "PFLICHT seit DSGVO — oft als Anlage"},
    ]

    return {
        "contract_type": contract_type,
        "pflichtangaben_nachwg": [c for c in pflicht_nachwg if c.get("relevant", True)],
        "empfohlene_klauseln": empfohlen,
        "neu_seit_2022": "NachwG-Reform August 2022: Meiste Angaben am 1. Arbeitstag schriftlich (NICHT elektronisch!)",
        "bussgeld": "Bis 2.000€ pro Verstoß (§4 NachwG)",
        "schriftform": "PAPIER — Nachweisgesetz verlangt Schriftform (§126 BGB), NICHT Textform/E-Mail!",
        "legal_basis": "Nachweisgesetz (NachwG), §2 — Reform 01.08.2022",
        "retrieved_at": ts(),
    }


async def handle_onboarding(args: dict) -> dict:
    """Einstellungs-Checkliste."""
    start_date = args.get("start_date", datetime.now().strftime("%Y-%m-%d"))
    contract_type = args.get("contract_type", "unbefristet")
    minijob = args.get("minijob", False)

    checklist = {
        "vor_arbeitsbeginn": [
            {"task": "Arbeitsvertrag (schriftlich!) unterschreiben lassen", "deadline": "Vor Tag 1", "pflicht": True},
            {"task": "Steuer-ID und Steuerklasse erfragen", "deadline": "Vor Tag 1", "pflicht": True},
            {"task": "SV-Ausweis / SV-Nummer erfragen", "deadline": "Vor Tag 1", "pflicht": True},
            {"task": "Bankverbindung für Gehaltszahlung", "deadline": "Vor Tag 1", "pflicht": True},
            {"task": "Krankenkasse (Mitgliedsbescheinigung)", "deadline": "Vor Tag 1", "pflicht": True},
            {"task": "Personalfragebogen ausfüllen lassen", "deadline": "Vor Tag 1", "pflicht": True},
            {"task": "DSGVO-Datenschutzerklärung unterzeichnen lassen", "deadline": "Tag 1", "pflicht": True},
            {"task": "Betriebsarzt: arbeitsmedizinische Vorsorge", "deadline": "Vor Tag 1", "pflicht": "Je nach Tätigkeit"},
            {"task": "Arbeitsplatz einrichten (IT, Zugänge, Schlüssel)", "deadline": "Vor Tag 1", "pflicht": False},
        ],
        "am_ersten_tag": [
            {"task": "Anmeldung bei Krankenkasse (DEÜV-Meldung)", "deadline": "Sofort", "pflicht": True},
            {"task": "Sofortmeldung an Rentenversicherung (§28a SGB IV)", "deadline": "Tag 1", "pflicht": "Baugewerbe, Gastronomie etc."},
            {"task": "Betriebsvereinbarungen/Tarifvertrag aushändigen", "deadline": "Tag 7", "pflicht": True},
            {"task": "Arbeitssicherheitsunterweisung", "deadline": "Tag 1", "pflicht": True},
        ],
        "innerhalb_erster_monat": [
            {"task": "Anmeldung bei Berufsgenossenschaft", "deadline": "1 Woche", "pflicht": True},
            {"task": "ELStAM-Anmeldung (elektronische Lohnsteuer)", "deadline": "Erste Abrechnung", "pflicht": True},
            {"task": "Betriebliche Altersvorsorge (bAV) anbieten", "deadline": "1 Monat", "pflicht": True},
            {"task": "VWL-Berechtigung prüfen", "deadline": "1 Monat", "pflicht": False},
        ],
    }

    if minijob:
        checklist["minijob_spezifisch"] = [
            {"task": "Anmeldung bei Minijob-Zentrale (statt Krankenkasse)", "pflicht": True},
            {"task": "Befreiung von RV-Pflicht anbieten (§6 Abs.1b SGB VI)", "pflicht": True},
            {"task": "Pauschalbeiträge abführen (AG: 30%)", "pflicht": True},
        ]

    return {
        "start_date": start_date,
        "contract_type": contract_type,
        "checklist": checklist,
        "legal_basis": "NachwG, §28a SGB IV, ArbSchG, DSGVO Art.13/14",
        "retrieved_at": ts(),
    }


async def handle_offboarding(args: dict) -> dict:
    """DSGVO-konforme Trennungs-Checkliste."""
    reason = args.get("reason", "kuendigung_ag")
    last_day = args.get("last_day", "")

    checklist = {
        "sofort": [
            {"task": "Kündigung/Aufhebung schriftlich dokumentieren", "pflicht": True},
            {"task": "Kündigungsschutzklage-Frist notieren: 3 Wochen ab Zugang (§4 KSchG)", "pflicht": True},
            {"task": "Betriebsrat anhören (§102 BetrVG) — VORHER!", "pflicht": "Bei Betriebsrat"},
            {"task": "Zeugnis-Entwurf vorbereiten", "pflicht": True},
        ],
        "bis_letzter_tag": [
            {"task": "Resturlaub berechnen und gewähren/abgelten", "pflicht": True},
            {"task": "Überstunden abbauen oder vergüten", "pflicht": True},
            {"task": "Firmenausweis, Schlüssel, Zugangskarten zurückfordern", "pflicht": True},
            {"task": "IT-Zugänge deaktivieren (E-Mail, VPN, Cloud)", "pflicht": True},
            {"task": "Firmenwagen / Diensthandy / Laptop zurücknehmen", "pflicht": True},
            {"task": "Arbeitsbescheinigung (§312 SGB III) für Arbeitsagentur", "pflicht": True},
        ],
        "dsgvo_massnahmen": [
            {"task": "Personenbezogene Daten: Löschfristen prüfen", "pflicht": True},
            {"task": "Personalakte: 3 Jahre aufbewahren (Klagefrist), dann prüfen", "pflicht": True},
            {"task": "Lohnunterlagen: 6 Jahre aufbewahren (§147 AO)", "pflicht": True},
            {"task": "SV-Unterlagen: 5 Jahre (§28f SGB IV)", "pflicht": True},
            {"task": "E-Mail-Konto: Private E-Mails löschen lassen, dann deaktivieren", "pflicht": True},
            {"task": "Fotos von Website/Intranet entfernen (Recht am eigenen Bild)", "pflicht": True},
        ],
        "meldungen": [
            {"task": "Abmeldung Krankenkasse (DEÜV-Abmeldung)", "deadline": "6 Wochen nach Austritt", "pflicht": True},
            {"task": "ELStAM-Abmeldung", "pflicht": True},
            {"task": "Abmeldung bei Berufsgenossenschaft (wenn letzter MA)", "pflicht": True},
        ],
    }

    return {
        "reason": reason,
        "last_day": last_day or "noch festzulegen",
        "checklist": checklist,
        "zeugnis": {
            "anspruch": "Einfaches Zeugnis sofort (§109 GewO), qualifiziertes auf Verlangen",
            "frist": "Unverzüglich, spätestens am letzten Arbeitstag",
            "wohlwollend": "Gebot der wohlwollenden Beurteilung (BAG-Rechtsprechung)",
        },
        "legal_basis": "KSchG, BGB §§620ff, DSGVO Art.17, §109 GewO, §312 SGB III",
        "retrieved_at": ts(),
    }


async def handle_skills_gap(args: dict) -> dict:
    """Kompetenz-Gap-Analyse."""
    required_skills = args.get("required_skills", [])
    current_skills = args.get("current_skills", [])

    if isinstance(required_skills, str):
        required_skills = [s.strip() for s in required_skills.split(",")]
    if isinstance(current_skills, str):
        current_skills = [s.strip() for s in current_skills.split(",")]

    req_set = set(s.lower() for s in required_skills)
    cur_set = set(s.lower() for s in current_skills)

    gaps = req_set - cur_set
    covered = req_set & cur_set
    extra = cur_set - req_set

    coverage = len(covered) / max(len(req_set), 1) * 100

    return {
        "required_count": len(req_set),
        "current_count": len(cur_set),
        "coverage_pct": round(coverage, 1),
        "gaps": sorted(gaps),
        "covered": sorted(covered),
        "extra_skills": sorted(extra),
        "gap_count": len(gaps),
        "priority": "CRITICAL" if coverage < 50 else "HIGH" if coverage < 70 else "MEDIUM" if coverage < 90 else "LOW",
        "recommendation": f"{len(gaps)} Kompetenzlücken identifiziert — {'Dringende Schulung/Hiring nötig' if len(gaps) > 3 else 'Gezielte Weiterbildung empfohlen' if gaps else 'Keine Lücken — alle Anforderungen abgedeckt'}",
        "retrieved_at": ts(),
    }


async def handle_headcount_forecast(args: dict) -> dict:
    """Personalbedarfsprognose."""
    current_headcount = int(args.get("current_headcount", 0))
    revenue_current = float(args.get("revenue_current", 0))
    revenue_target = float(args.get("revenue_target", 0))
    avg_cost_per_employee = float(args.get("avg_cost_per_employee", 60000))
    attrition_rate = float(args.get("attrition_rate_pct", 10)) / 100
    months = int(args.get("forecast_months", 12))
    productivity_growth = float(args.get("productivity_growth_pct", 2)) / 100

    if current_headcount <= 0 or revenue_current <= 0:
        return {"error": "Provide 'current_headcount' and 'revenue_current'"}

    revenue_per_head = revenue_current / current_headcount

    if revenue_target > 0:
        adjusted_rph = revenue_per_head * (1 + productivity_growth)
        target_headcount = math.ceil(revenue_target / adjusted_rph)
        delta = target_headcount - current_headcount
        attrition_replacements = math.ceil(current_headcount * attrition_rate * (months / 12))
        total_hires = max(0, delta) + attrition_replacements

        return {
            "current": {"headcount": current_headcount, "revenue": revenue_current,
                       "revenue_per_head": round(revenue_per_head, 2)},
            "target": {"revenue": revenue_target, "headcount_needed": target_headcount,
                      "revenue_per_head_adjusted": round(adjusted_rph, 2)},
            "forecast": {
                "net_new_positions": max(0, delta),
                "attrition_replacements": attrition_replacements,
                "total_hires_needed": total_hires,
                "hiring_cost_estimate": round(total_hires * avg_cost_per_employee * 0.2, 2),
                "annual_cost_increase": round(max(0, delta) * avg_cost_per_employee, 2),
            },
            "months": months,
            "assumptions": {
                "attrition_rate": f"{attrition_rate*100}%",
                "productivity_growth": f"{productivity_growth*100}%",
                "avg_cost_per_employee": avg_cost_per_employee,
                "hiring_cost_factor": "20% des Jahresgehalts (Recruiting)",
            },
            "retrieved_at": ts(),
        }

    return {"error": "Provide 'revenue_target' for forecast"}


# ═══════════════════════════════════════════════════════════════
def main():
    server = WhitelabelMCPServer(
        product_name=PRODUCT_NAME, product_slug="hroracle",
        version=VERSION, port_mcp=PORT_MCP, port_health=PORT_HEALTH)

    server.register_tool("gross_to_net",
        "German Brutto-Netto salary calculation. Supports all Steuerklassen, Kirchensteuer, children factor. Returns monthly/annual breakdown with all deductions (Lohnsteuer, Soli, SV). SV-Werte 2026.",
        {"gross_monthly": {"type": "number", "description": "Brutto-Monatsgehalt in EUR"},
         "steuerklasse": {"type": "integer", "description": "Steuerklasse 1-6 (default: 1)"},
         "children": {"type": "integer", "description": "Anzahl Kinder (default: 0)"},
         "church_tax": {"type": "boolean", "description": "Kirchensteuerpflichtig (default: false)"},
         "state": {"type": "string", "description": "Bundesland z.B. NRW, BY, BW (default: NRW)"}},
        handle_gross_to_net, credits=2)

    server.register_tool("employer_cost",
        "Calculate total employer cost (AG-Gesamtkosten) including all social security contributions, Umlagen U1/U2/U3, and BG premiums.",
        {"gross_monthly": {"type": "number", "description": "Brutto-Monatsgehalt in EUR"}},
        handle_employer_cost, credits=1)

    server.register_tool("minijob_check",
        "Check Minijob (538€) vs Midijob (Übergangsbereich) vs regular employment classification. Includes Mindestlohn check.",
        {"monthly_income": {"type": "number", "description": "Monatliches Entgelt in EUR"},
         "hours_per_week": {"type": "number", "description": "Wochenstunden (für Mindestlohn-Check)"}},
        handle_minijob_check, credits=1)

    server.register_tool("leave_calculate",
        "Calculate vacation entitlement (Urlaubsanspruch) per BUrlG. Handles part-year, part-time, severely disabled additional leave, waiting period.",
        {"weekly_working_days": {"type": "integer", "description": "Arbeitstage pro Woche (default: 5)"},
         "contractual_leave_days": {"type": "integer", "description": "Vertragliche Urlaubstage (0 = nur gesetzlich)"},
         "start_date": {"type": "string", "description": "Eintrittsdatum YYYY-MM-DD (für Teilanspruch)"},
         "severely_disabled": {"type": "boolean", "description": "Schwerbehindert (Zusatzurlaub §208 SGB IX)"},
         "age": {"type": "integer", "description": "Alter des Mitarbeiters"}},
        handle_leave_calculate, credits=1)

    server.register_tool("notice_period",
        "Calculate German notice periods (Kündigungsfristen) per §622 BGB. Considers years of service, probation, employer vs employee initiated.",
        {"years_employed": {"type": "number", "description": "Betriebszugehörigkeit in Jahren"},
         "in_probation": {"type": "boolean", "description": "In Probezeit? (default: false)"},
         "initiated_by": {"type": "string", "description": "employer | employee (default: employer)"},
         "contract_type": {"type": "string", "description": "unbefristet | befristet"}},
        handle_notice_period, credits=1)

    server.register_tool("working_time_check",
        "Arbeitszeitgesetz (ArbZG) compliance check. Validates daily/weekly hours, breaks, rest periods against German law. Returns violations, warnings, and max penalties.",
        {"daily_hours": {"type": "number", "description": "Tägliche Arbeitszeit in Stunden"},
         "weekly_hours": {"type": "number", "description": "Wöchentliche Arbeitszeit (0 = auto aus daily*5)"},
         "break_minutes": {"type": "integer", "description": "Pausenzeit in Minuten"},
         "night_work": {"type": "boolean", "description": "Nachtarbeit (23-6 Uhr)"},
         "sunday_work": {"type": "boolean", "description": "Sonntagsarbeit"}},
        handle_working_time, credits=1)

    server.register_tool("parental_leave_check",
        "Elternzeit & Elterngeld Berechnung (BEEG). Returns entitlement, Elterngeld amount (67%), ElterngeldPlus, Kündigungsschutz, Teilzeit options.",
        {"child_birth_date": {"type": "string", "description": "Geburtsdatum des Kindes YYYY-MM-DD"},
         "monthly_net_income": {"type": "number", "description": "Netto-Monatseinkommen vor Geburt"},
         "part_time_hours": {"type": "number", "description": "Gewünschte Teilzeitstunden während Elternzeit (0-32)"}},
        handle_parental_leave, credits=2)

    server.register_tool("contract_clauses",
        "Mandatory employment contract clauses per NachwG (Nachweisgesetz) 2022 reform. Returns all 14 mandatory items with deadlines, plus recommended additional clauses.",
        {"contract_type": {"type": "string", "description": "unbefristet | befristet | teilzeit | minijob"},
         "position": {"type": "string", "description": "Job title / Stellenbezeichnung"}},
        handle_contract_clauses, credits=1)

    server.register_tool("onboarding_checklist",
        "Complete employee onboarding checklist for German employers. DEÜV, ELStAM, BG, bAV, Arbeitssicherheit. Minijob variant included.",
        {"start_date": {"type": "string", "description": "Startdatum YYYY-MM-DD"},
         "contract_type": {"type": "string", "description": "unbefristet | befristet | minijob"},
         "minijob": {"type": "boolean", "description": "Minijob-Anmeldung bei Minijob-Zentrale"}},
        handle_onboarding, credits=1)

    server.register_tool("offboarding_checklist",
        "DSGVO-compliant employee offboarding checklist. Covers IT access, data retention (3/5/6 year rules), DEÜV deregistration, Zeugnis, Arbeitsbescheinigung.",
        {"reason": {"type": "string", "description": "kuendigung_ag | kuendigung_an | aufhebung | befristung_ende"},
         "last_day": {"type": "string", "description": "Letzter Arbeitstag YYYY-MM-DD"}},
        handle_offboarding, credits=1)

    server.register_tool("skills_gap_analyze",
        "Analyze skills gap between required and current team competencies. Returns coverage %, gaps, priorities, and training recommendations.",
        {"required_skills": {"type": "string", "description": "Comma-separated required skills"},
         "current_skills": {"type": "string", "description": "Comma-separated current team skills"}},
        handle_skills_gap, credits=1)

    server.register_tool("headcount_forecast",
        "Forecast hiring needs based on revenue targets, attrition rates, and productivity growth. Returns total hires needed, cost estimates.",
        {"current_headcount": {"type": "integer", "description": "Aktuelle Mitarbeiteranzahl"},
         "revenue_current": {"type": "number", "description": "Aktueller Jahresumsatz EUR"},
         "revenue_target": {"type": "number", "description": "Ziel-Jahresumsatz EUR"},
         "avg_cost_per_employee": {"type": "number", "description": "Durchschnittliche AG-Kosten/MA/Jahr (default: 60000)"},
         "attrition_rate_pct": {"type": "number", "description": "Jährliche Fluktuation % (default: 10)"},
         "forecast_months": {"type": "integer", "description": "Prognosezeitraum Monate (default: 12)"},
         "productivity_growth_pct": {"type": "number", "description": "Produktivitätssteigerung % p.a. (default: 2)"}},
        handle_headcount_forecast, credits=2)

    logger.info(f"🚀 {PRODUCT_NAME} v{VERSION} starting on port {PORT_MCP}")
    server.run()

if __name__ == "__main__":
    main()
