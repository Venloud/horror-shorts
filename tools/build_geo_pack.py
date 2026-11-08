"""Build assets/geo/ (offline map pack for the Hollywood place graphics) from Natural Earth (public domain):
countries (50m), states / provinces (10m, simplified), cities (populated places), plus flag PNGs rendered from the
Noto Color Emoji font (OFL / Apache-2.0). Run once by a maintainer; production only reads the result.
  python tools/build_geo_pack.py <dir with the three Natural Earth geojson files>
"""
import json
import sys
from pathlib import Path

from shapely.geometry import shape, mapping

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "geo"


def rings(geom, tol):
    g = shape(geom).simplify(tol, preserve_topology=True)
    polys = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
    out = []
    for p in polys:
        if p.is_empty or p.area < tol * tol * 4:
            continue
        out.append([[round(x, 2), round(y, 2)] for x, y in p.exterior.coords])
    return out


def main(src: str) -> None:
    src = Path(src)
    OUT.mkdir(parents=True, exist_ok=True)
    countries = []
    for f in json.loads((src / "ne_50m_admin_0_countries.geojson").read_text())["features"]:
        p = f["properties"]
        iso2 = p.get("ISO_A2_EH") if p.get("ISO_A2_EH") not in (None, "-99") else p.get("ISO_A2")
        if not iso2 or iso2 == "-99":
            continue
        names = {p.get(k) for k in ("NAME", "NAME_LONG", "ADMIN", "FORMAL_EN", "NAME_EN", "NAME_SORT") if p.get(k)}
        c = shape(f["geometry"]).representative_point()
        countries.append({"iso2": iso2, "name": p.get("NAME"), "names": sorted(names),
                          "lon": round(p.get("LABEL_X") or c.x, 2), "lat": round(p.get("LABEL_Y") or c.y, 2),
                          "rings": rings(f["geometry"], 0.04)})
    (OUT / "countries.json").write_text(json.dumps(countries, separators=(",", ":")))
    admin1 = []
    for f in json.loads((src / "ne_10m_admin_1_states_provinces.geojson").read_text())["features"]:
        p = f["properties"]
        if not p.get("name") or not p.get("iso_a2") or p.get("iso_a2") == "-1":
            continue
        names = {p.get(k) for k in ("name", "name_en", "name_alt") if p.get(k)}
        names = {n for x in names for n in str(x).split("|") if len(n) > 2}
        c = shape(f["geometry"]).representative_point()
        admin1.append({"iso2": p["iso_a2"], "name": p["name"], "names": sorted(names),
                       "type": p.get("type_en") or "Region", "lon": round(p.get("longitude") or c.x, 2),
                       "lat": round(p.get("latitude") or c.y, 2), "rings": rings(f["geometry"], 0.02)})
    (OUT / "admin1.json").write_text(json.dumps(admin1, separators=(",", ":")))
    cities = []
    for f in json.loads((src / "ne_10m_populated_places_simple.geojson").read_text())["features"]:
        p = f["properties"]
        if (p.get("scalerank") or 10) > 8 or not p.get("iso_a2") or p.get("iso_a2") == "-99":
            continue
        cities.append({"name": p["name"], "iso2": p["iso_a2"], "admin1": p.get("adm1name") or "",
                       "lon": round(p["longitude"], 3), "lat": round(p["latitude"], 3),
                       "rank": p.get("scalerank")})
    (OUT / "cities.json").write_text(json.dumps(cities, separators=(",", ":")))
    flags(sorted({c["iso2"] for c in countries}))
    (OUT / "SOURCES.md").write_text(
        "# Offline geo pack\n\n- countries.json: Natural Earth 1:50m Admin 0 (public domain), simplified 0.04 deg.\n"
        "- admin1.json: Natural Earth 1:10m Admin 1 states / provinces (public domain), simplified 0.02 deg.\n"
        "- cities.json: Natural Earth 1:10m populated places, scalerank <= 8 (public domain).\n"
        "- flags/*.png: rendered from the Noto Color Emoji font (SIL OFL 1.1 font; Apache-2.0 images).\n"
        "Built by tools/build_geo_pack.py; https://www.naturalearthdata.com/about/terms-of-use/\n")
    print(len(countries), "countries", len(admin1), "admin1", len(cities), "cities")


def flags(codes):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)
    d = OUT / "flags"
    d.mkdir(exist_ok=True)
    for iso in codes:
        if len(iso) != 2 or not iso.isalpha():
            continue
        txt = "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in iso.upper())
        im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((8, 8), txt, font=font, embedded_color=True)
        box = im.getbbox()
        if box and box[2] - box[0] > 60:
            im.crop(box).save(d / f"{iso.upper()}.png", optimize=True)


if __name__ == "__main__":
    main(sys.argv[1])
