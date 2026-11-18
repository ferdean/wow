-- The Phase 0 PDF's filter: code that breaks anywhere sensible, bold text
-- in red, "Refuted" in red, table headers in bold.
local escapes = {
  ["\\"] = "\\textbackslash{}", ["{"] = "\\{", ["}"] = "\\}",
  ["#"] = "\\#", ["$"] = "\\$", ["%"] = "\\%", ["&"] = "\\&",
  ["_"] = "\\_", ["~"] = "\\textasciitilde{}", ["^"] = "\\textasciicircum{}",
}

local function escape(text)
  return (text:gsub("[\\{}#$%%&_~^]", escapes))
end

local function breakable(text)
  local out = escape(text)
  out = out:gsub("%-", "-\\allowbreak{}")
  out = out:gsub(" ", " \\allowbreak{}")
  out = out:gsub(":", ":\\allowbreak{}")
  out = out:gsub("/", "/\\allowbreak{}")
  return out
end

function Code(el)
  return pandoc.RawInline("latex", "\\texttt{" .. breakable(el.text) .. "}")
end

function Strong(el)
  local result = { pandoc.RawInline("latex", "\\textcolor{wowred}{\\textbf{") }
  for _, inline in ipairs(el.content) do
    table.insert(result, inline)
  end
  table.insert(result, pandoc.RawInline("latex", "}}"))
  return result
end

function Str(el)
  if el.text == "Refuted" then
    return pandoc.RawInline("latex", "\\textcolor{wowred}{\\textbf{Refuted}}")
  end
end

local function bold_cell(cell)
  for _, block in ipairs(cell.contents) do
    if block.t == "Plain" or block.t == "Para" then
      table.insert(block.content, 1, pandoc.RawInline("latex", "\\textbf{"))
      table.insert(block.content, pandoc.RawInline("latex", "}"))
    end
  end
  return cell
end

function Table(tbl)
  for _, row in ipairs(tbl.head.rows) do
    for i, cell in ipairs(row.cells) do
      row.cells[i] = bold_cell(cell)
    end
  end
  return tbl
end
