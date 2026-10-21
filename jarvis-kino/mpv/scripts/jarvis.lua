-- Jarvis Kino: Streaming-Funktionen für mpv (Jarvis-Design: dunkle Graustufen)
--  * Folgen & Staffeln als scrollbares Menü (Taste E / Knopf unten rechts)
--  * "Nächste Folge" mit Countdown, vorherige/nächste Folge (N / P)
--  * "Intro überspringen" (Kapitel oder Serien-Schätzung, Taste S)
--  * Fortsetzen an der letzten Stelle, Pause-Ansicht "Du siehst gerade"
--  * Wiederaufnahme bei Verbindungsabbruch an derselben Stelle
-- Exit-Codes für die App: 4 = Verbindung dauerhaft weg, 5 = Video nicht ladbar.

local mp = require 'mp'
local utils = require 'mp.utils'
local msg = require 'mp.msg'

local opts = { daten = "" }
require('mp.options').read_options(opts, "jarvis")

local daten = { folgen = {}, start = {} }
local folgen_nach_id = {}
local id_nach_url = {}       -- aufgelöste Mediathek-Adressen -> Kennung
local stelle = {}            -- id -> letzte bekannte Position
local versuche = {}          -- id -> Zahl der Neuversuche
local eof_bei = {}           -- id -> Position beim letzten vorzeitigen Ende
local sitzung_lief = false
local aktuelle_id = nil
local fortsetzen_bei = nil
local intro_erledigt = {}
local naechste_seit = nil
local pause_seit = nil
local WARTEZEITEN = { 2, 4, 8, 15, 30 }

local function daten_laden()
    if opts.daten == "" then return end
    local datei = io.open(opts.daten, "r")
    if not datei then return end
    local d = utils.parse_json(datei:read("*a"))
    datei:close()
    if type(d) ~= "table" then return end
    daten = d
    daten.folgen = d.folgen or {}
    for i, f in ipairs(daten.folgen) do
        f.index = i
        folgen_nach_id[f.id] = f
        if f.url then id_nach_url[f.url] = f.id end
    end
    for id, pos in pairs(d.start or {}) do stelle[id] = pos end
end
daten_laden()

local function id_aus(pfad)
    if not pfad then return nil end
    if id_nach_url[pfad] then return id_nach_url[pfad] end
    local id = pfad:match("/api/video/[%a_]+/([^/?#]+)")
    return id and id:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end) or nil
end

local function zeit_text(s)
    s = math.floor(s or 0)
    local h, m, sek = math.floor(s / 3600), math.floor(s / 60) % 60, s % 60
    if h > 0 then return string.format("%d:%02d:%02d", h, m, sek) end
    return string.format("%d:%02d", m, sek)
end

local function ist_serie() return #daten.folgen > 1 end

-- Im Abspann (letzte 5 %, höchstens 60 s) gilt eine Folge als gesehen.
local function fast_fertig(pos, dauer)
    return dauer and dauer > 0 and pos >= dauer - math.min(60, dauer * 0.05)
end

local function index_von(id)
    for i, eintrag in ipairs(mp.get_property_native("playlist") or {}) do
        if id_aus(eintrag.filename) == id then return i - 1 end
    end
    return nil
end

local function hat_naechste()
    return mp.get_property_number("playlist-pos", 0) < mp.get_property_number("playlist-count", 1) - 1
end

-- ------------------------------------------------------------ Laden & Start
mp.add_hook("on_load", 50, function()
    local id = id_aus(mp.get_property("stream-open-filename") or mp.get_property("path"))
    aktuelle_id = id
    fortsetzen_bei = nil
    naechste_seit = nil
    if not id then return end
    local f = folgen_nach_id[id]
    if f and f.anzeige and f.anzeige ~= "" then
        mp.set_property("file-local-options/force-media-title", f.anzeige)
    end
    local pos = stelle[id]
    if pos == nil and f then pos = f.position end
    local dauer = (f and f.dauer) or 0
    if pos and pos > 5 and not fast_fertig(pos, dauer) then
        local start = math.max(0, pos - 2)
        mp.set_property("file-local-options/start", string.format("%.2f", start))
        fortsetzen_bei = start
    end
end)

mp.register_event("file-loaded", function()
    if fortsetzen_bei and (versuche[aktuelle_id] or 0) == 0 then
        mp.osd_message("Fortgesetzt bei " .. zeit_text(fortsetzen_bei) .. "   ·   Pos1 = von vorn", 4)
    end
end)

local bereit = false  -- erst nach dem Sprung zur gespeicherten Stelle Positionen übernehmen
mp.register_event("start-file", function() bereit = false end)
mp.register_event("playback-restart", function() bereit = true end)

mp.observe_property("time-pos", "number", function(_, t)
    if not t or not aktuelle_id or not bereit then return end
    stelle[aktuelle_id] = t
    if t > 1 then sitzung_lief = true end
end)

-- ------------------------------------------------- Abbrüche & Folgenende
local function neu_versuchen(grund, id, nach_fehler)
    id = id or aktuelle_id
    if not id then return end
    versuche[id] = (versuche[id] or 0) + 1
    local n = versuche[id]
    if n > #WARTEZEITEN then
        mp.osd_message("Keine Verbindung – Jarvis Kino sucht eine andere Adresse …", 5)
        mp.add_timeout(1, function() mp.command("quit 4") end)
        return
    end
    local index = index_von(id)
    if nach_fehler then
        mp.commandv("stop", "keep-playlist")
    else
        mp.set_property_bool("pause", true)
    end
    local warte = WARTEZEITEN[n]
    msg.warn(string.format("%s bei %s, Versuch %d in %d s", grund, zeit_text(stelle[id]), n, warte))
    mp.osd_message(string.format("%s – neuer Versuch in %d s (%d/%d) …", grund, warte, n, #WARTEZEITEN), warte + 1)
    mp.add_timeout(warte, function()
        if index then mp.commandv("playlist-play-index", tostring(index)) end
        mp.set_property_bool("pause", false)
    end)
end

local function folge_zu_ende()
    if hat_naechste() then
        mp.command("playlist-next")
    else
        mp.command("quit 0")
    end
end

mp.observe_property("eof-reached", "bool", function(_, eof)
    if not eof or not aktuelle_id then return end
    local dauer = mp.get_property_number("duration", 0)
    local pos = stelle[aktuelle_id] or 0
    if dauer > 0 and dauer - pos > 30 then
        -- Zweimal an derselben Stelle zu Ende = Datei ist wirklich so kurz.
        local vorher = eof_bei[aktuelle_id]
        if not (vorher and math.abs(vorher - pos) < 10) then
            eof_bei[aktuelle_id] = pos
            neu_versuchen("Verbindung unterbrochen")
            return
        end
    end
    folge_zu_ende()
end)

mp.register_event("end-file", function(e)
    if e.reason ~= "error" then return end
    if not sitzung_lief then
        msg.error("Video ließ sich nicht laden: " .. tostring(e.file_error))
        mp.command("quit 5")
        return
    end
    neu_versuchen("Verbindung unterbrochen", aktuelle_id, true)
end)

-- Nach 30 s ungestörter Wiedergabe gelten frühere Abbrüche als erledigt.
mp.add_periodic_timer(30, function()
    if aktuelle_id and not mp.get_property_bool("pause") and not mp.get_property_bool("paused-for-cache") then
        versuche[aktuelle_id] = 0
    end
end)

-- ------------------------------------------------------------- Knöpfe
local overlay = mp.create_osd_overlay("ass-events")
local knopf = nil      -- { art, text, aktion, x, y, w, h }
local klick_aktiv = false

local function ass_text(s)
    return (s or ""):gsub("\\", "\\\\"):gsub("{", "\\{"):gsub("}", "\\}"):gsub("\n", " ")
end

local function knopf_lage()
    if not knopf then return end
    local w, h = mp.get_osd_size()
    if not w or w <= 0 or h <= 0 then w, h = 1280, 720 end
    knopf.fs = math.max(18, h * 0.03)
    knopf.h = knopf.fs * 2.2
    knopf.w = (#knopf.text * 0.55 + 2.6) * knopf.fs
    knopf.x = w - knopf.w - w * 0.04
    knopf.y = h * 0.74
end

-- Rechteck mit runden Ecken (ASS-Zeichnung), wie die Jarvis-Kacheln
local function abgerundet(w, h, r)
    return string.format("m %d 0 l %d 0 b %d 0 %d 0 %d %d l %d %d b %d %d %d %d %d %d l %d %d b %d %d 0 %d 0 %d l 0 %d b 0 0 0 0 %d 0",
        r, w - r, w, w, w, r, w, h - r, w, h, w, h, w - r, h, r, h, 0, h, h, h - r, r, r)
end

local function maus_ueber()
    if not knopf or not knopf.x then return false end
    local mx, my = mp.get_mouse_pos()
    if not mx or not my then return false end
    return mx >= knopf.x and mx <= knopf.x + knopf.w and my >= knopf.y and my <= knopf.y + knopf.h
end

local function knopf_ausloesen()
    if not knopf then return false end
    local k = knopf
    knopf = nil
    k.aktion()
    return true
end

local function klick_binden(an)
    if an and not klick_aktiv then
        mp.add_forced_key_binding("MBTN_LEFT", "jarvis-knopf-klick", function() knopf_ausloesen() end)
        klick_aktiv = true
    elseif not an and klick_aktiv then
        mp.remove_key_binding("jarvis-knopf-klick")
        klick_aktiv = false
    end
end

local function zeichnen()
    local w, h = mp.get_osd_size()
    if not w or w <= 0 or h <= 0 then return end
    overlay.res_x, overlay.res_y = w, h
    local teile = {}

    if pause_seit and mp.get_time() - pause_seit > 5 and aktuelle_id then
        local f = folgen_nach_id[aktuelle_id]
        local gross = h * 0.055
        local klein = h * 0.026
        local x, y = w * 0.06, h * 0.36
        teile[#teile + 1] = string.format("{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&\\1a&H60&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}", w, w, h, h)
        teile[#teile + 1] = string.format("{\\an7\\pos(%d,%d)\\fnNoto Sans\\fs%d\\bord0\\shad0\\1c&HB3B3B3&}Du siehst gerade", x, y, klein)
        local titel = daten.serie or (f and f.titel) or mp.get_property("media-title", "")
        teile[#teile + 1] = string.format("{\\an7\\pos(%d,%d)\\fnNoto Sans\\b1\\fs%d\\bord0\\shad1\\1c&HFFFFFF&}%s", x, y + klein * 1.6, gross, ass_text(titel))
        if f and ist_serie() then
            local zeile = (f.staffel and ("Staffel " .. f.staffel .. ", ") or "") .. "Folge " .. tostring(f.folge or f.index)
            if f.titel and f.titel ~= "" and f.titel ~= titel then zeile = zeile .. ": " .. f.titel end
            teile[#teile + 1] = string.format("{\\an7\\pos(%d,%d)\\fnNoto Sans\\fs%d\\bord0\\shad1\\1c&HFFFFFF&}%s", x, y + klein * 1.6 + gross * 1.3, klein * 1.15, ass_text(zeile))
        end
    end

    if knopf then
        knopf_lage()
        local fs = knopf.fs
        -- Hell = Hauptaktion bzw. Maus darüber; sonst halbtransparentes Dunkelgrau
        local hell = knopf.art == "naechste" or maus_ueber()
        local hinter = hell and "&HEAE5E5&" or "&H1E1C1C&"     -- #e5e5ea / #1c1c1e (BGR)
        local schrift = hell and "&H0B0A0A&" or "&HF7F5F5&"    -- #0a0a0b / #f5f5f7
        teile[#teile + 1] = string.format(
            "{\\an7\\pos(%d,%d)\\bord1\\shad0\\blur0.6\\1c%s\\1a&H%s&\\3c&HF5EBEB&\\3a&H%s&\\p1}%s{\\p0}",
            knopf.x, knopf.y, hinter, hell and "08" or "38", hell and "FF" or "A0",
            abgerundet(knopf.w, knopf.h, knopf.h * 0.3))
        teile[#teile + 1] = string.format("{\\an5\\pos(%d,%d)\\fnNoto Sans\\b1\\fs%d\\bord0\\shad0\\1c%s}%s",
            knopf.x + knopf.w / 2, knopf.y + knopf.h / 2, fs, schrift, ass_text(knopf.text))
    end

    overlay.data = table.concat(teile, "\n")
    overlay:update()
end

local function kapitel_suche(muster_liste)
    local kapitel = mp.get_property_native("chapter-list") or {}
    for i, k in ipairs(kapitel) do
        local titel = (k.title or ""):lower()
        for _, muster in ipairs(muster_liste) do
            if titel:find(muster) then
                return k.time, (kapitel[i + 1] and kapitel[i + 1].time or nil), kapitel
            end
        end
    end
    return nil, nil, kapitel
end

local function intro_bereich(t)
    local von, bis, kapitel = kapitel_suche({ "intro", "vorspann", "opening", "titelsequenz", "^op$" })
    if von and bis and t >= von and t < bis - 1 then
        return { text = "Intro überspringen", ziel = bis }
    end
    -- Ohne Kapitel nur schätzen, wenn die Folge von vorn läuft (nicht beim Fortsetzen).
    if daten.intro_schaetzen and ist_serie() and #kapitel == 0 and not fortsetzen_bei and t >= 15 and t < 150 then
        return { text = "Intro überspringen  +85 s", ziel = t + 85 }
    end
end

local function weiter_zur_naechsten()
    naechste_seit = nil
    if hat_naechste() then
        mp.command("playlist-next")
        mp.set_property_bool("pause", false)
    else
        mp.osd_message("Das war die letzte Folge", 2)
    end
end

local function tick()
    local t = mp.get_property_number("time-pos")
    local alt = knopf and knopf.art
    knopf = nil
    if t and aktuelle_id then
        local dauer = mp.get_property_number("duration", 0)
        local intro = not intro_erledigt[aktuelle_id] and intro_bereich(t)
        if intro then
            local ziel = intro.ziel
            knopf = { art = "intro", text = intro.text, aktion = function()
                intro_erledigt[aktuelle_id] = true
                mp.commandv("seek", tostring(ziel), "absolute")
            end }
        elseif ist_serie() and hat_naechste() and dauer > 120 then
            local abspann = kapitel_suche({ "abspann", "credits", "outro", "ending", "^ed$" })
            local ab = abspann or (dauer - 25)
            if t >= ab then
                local pausiert = mp.get_property_bool("pause")
                if not naechste_seit then naechste_seit = mp.get_time() end
                if pausiert then naechste_seit = naechste_seit + 0.25 end
                local rest = math.ceil(10 - (mp.get_time() - naechste_seit))
                if rest <= 0 and not pausiert then
                    weiter_zur_naechsten()
                else
                    knopf = { art = "naechste", text = "Nächste Folge  ▸  " .. math.max(rest, 0), aktion = weiter_zur_naechsten }
                end
            else
                naechste_seit = nil
            end
        end
    end
    knopf_lage()
    klick_binden(knopf ~= nil and maus_ueber())
    if knopf or alt or pause_seit then zeichnen() end
end
mp.add_periodic_timer(0.25, tick)
mp.observe_property("osd-dimensions", "native", function() zeichnen() end)

mp.observe_property("pause", "bool", function(_, p)
    pause_seit = p and mp.get_time() or nil
    zeichnen()
end)

-- ------------------------------------------------------------- Folgen-Menü
local function folgen_menue()
    if #daten.folgen < 2 then
        mp.osd_message("Keine weiteren Folgen", 2)
        return
    end
    local staffeln, reihenfolge = {}, {}
    for _, f in ipairs(daten.folgen) do
        local s = f.staffel or 0
        if not staffeln[s] then
            staffeln[s] = {}
            reihenfolge[#reihenfolge + 1] = s
        end
        table.insert(staffeln[s], f)
    end

    local function eintrag(f)
        local pos = stelle[f.id] or f.position or 0
        local dauer = f.dauer or 0
        local hinweis
        if f.id == aktuelle_id then
            hinweis = "▶ läuft"
        elseif f.gesehen or fast_fertig(pos, dauer) then
            hinweis = "✓ gesehen"
        elseif pos > 30 then
            hinweis = zeit_text(pos) .. (dauer > 0 and (" / " .. zeit_text(dauer)) or "")
        elseif dauer > 0 then
            hinweis = math.floor(dauer / 60 + 0.5) .. " Min."
        end
        local name = (f.titel and f.titel ~= "") and f.titel or ("Folge " .. tostring(f.folge or f.index))
        local nummer = f.folge and (tostring(f.folge) .. ".  ") or ""
        return {
            title = nummer .. name,
            hint = hinweis,
            value = { "playlist-play-index", tostring(f.index - 1) },
            active = f.id == aktuelle_id,
        }
    end

    local items, auswahl, offen = {}, 1, nil
    if #reihenfolge > 1 then
        for i, s in ipairs(reihenfolge) do
            local unter, enthaelt = {}, false
            for j, f in ipairs(staffeln[s]) do
                unter[#unter + 1] = eintrag(f)
                if f.id == aktuelle_id then enthaelt = true; unter.auswahl = j end
            end
            local id = "staffel-" .. tostring(s)
            items[#items + 1] = {
                id = id,
                title = s == 0 and "Weitere Folgen" or ("Staffel " .. tostring(s)),
                hint = #unter .. " Folgen",
                items = unter,
                selected_index = unter.auswahl,
                active = enthaelt,
            }
            unter.auswahl = nil
            if enthaelt then auswahl = i; offen = id end
        end
    else
        for i, f in ipairs(daten.folgen) do
            items[#items + 1] = eintrag(f)
            if f.id == aktuelle_id then auswahl = i end
        end
    end
    local menue = {
        type = "jarvis-folgen",
        title = daten.serie or "Folgen",
        items = items,
        selected_index = auswahl,
        search_style = "on_demand",
    }
    if offen then
        mp.commandv("script-message-to", "uosc", "open-menu", utils.format_json(menue), offen)
    else
        mp.commandv("script-message-to", "uosc", "open-menu", utils.format_json(menue))
    end
end

mp.add_key_binding(nil, "folgen", folgen_menue)
mp.add_key_binding(nil, "naechste", function()
    if hat_naechste() then weiter_zur_naechsten() else mp.osd_message("Das war die letzte Folge", 2) end
end)
mp.add_key_binding(nil, "vorherige", function()
    if mp.get_property_number("playlist-pos", 0) > 0 then
        mp.command("playlist-prev")
        mp.set_property_bool("pause", false)
    else
        mp.osd_message("Das ist die erste Folge", 2)
    end
end)
mp.add_key_binding(nil, "intro", function()
    if knopf and knopf.art == "intro" then knopf_ausloesen() else mp.osd_message("Hier gibt es kein Intro zu überspringen", 2) end
end)
mp.add_key_binding(nil, "aktion", function()
    if not knopf_ausloesen() then mp.command("cycle pause") end
end)
