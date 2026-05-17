import { useState, useCallback } from "react"
import axios from "axios"

const API = "http://localhost:8000/api"

const TYPE_COLORS = {
  "HLO":   { accent: "#e94560", bg: "#2a0f18", label: "Henkilo" },
  "ORG":   { accent: "#E8001C", bg: "#0a1f2e", label: "Organisaatio" },
  "PAIK":  { accent: "#40916c", bg: "#0a1f14", label: "Sijainti" },
  "YTUN":  { accent: "#9b5de5", bg: "#1a0a2e", label: "Y-tunnus" },
  "HETU":  { accent: "#f4845f", bg: "#2a1000", label: "Henkilotunnus" },
  "IBAN":  { accent: "#48cae4", bg: "#0a1a2a", label: "IBAN" },
  "PUH":   { accent: "#aacc00", bg: "#1a1f00", label: "Puhelin" },
  "EMAIL": { accent: "#ff6b9d", bg: "#2a0a1a", label: "Sahkoposti" },
  "MUUT":  { accent: "#aaaaaa", bg: "#1a1a1a", label: "Muu" },
}

const getTS = (code) => {
  const key = code ? code.replace("\u00d6","O").replace("\u00c4","A") : "MUUT"
  return TYPE_COLORS[key] || TYPE_COLORS["MUUT"]
}

function highlightText(text, mappings) {
  if (!text || !mappings.length) return [{ text, highlight: null }]
  const hits = []
  for (const m of mappings) {
    const escaped = m.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    try {
      const re = new RegExp(escaped, "gi")
      let match
      while ((match = re.exec(text)) !== null) {
        hits.push({ start: match.index, end: match.index + match[0].length, mapping: m })
      }
    } catch(e) {}
  }
  if (!hits.length) return [{ text, highlight: null }]
  hits.sort((a, b) => a.start - b.start)
  const deduped = [hits[0]]
  for (let i = 1; i < hits.length; i++) {
    if (hits[i].start >= deduped[deduped.length-1].end) deduped.push(hits[i])
  }
  const segments = []
  let pos = 0
  for (const h of deduped) {
    if (h.start > pos) segments.push({ text: text.slice(pos, h.start), highlight: null })
    segments.push({ text: text.slice(h.start, h.end), highlight: h.mapping })
    pos = h.end
  }
  if (pos < text.length) segments.push({ text: text.slice(pos), highlight: null })
  return segments
}

export default function App() {
  const [phase, setPhase] = useState("upload")
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [mappings, setMappings] = useState([])
  const [filename, setFilename] = useState("")
  const [originalText, setOriginalText] = useState("")
  const [anonymizedText, setAnonymizedText] = useState("")
  const [llmResponse, setLlmResponse] = useState("")
  const [deanonymizedText, setDeanonymizedText] = useState("")
  const [manualValue, setManualValue] = useState("")
  const [manualType, setManualType] = useState("CUSTOM")
  const [copied, setCopied] = useState(false)
  const [hoveredMapping, setHoveredMapping] = useState(null)

  const handleFile = useCallback(async (file) => {
    if (!file || !file.name.endsWith(".pdf") && !file.name.endsWith(".docx")) { setError("Vain PDF- ja Word-tiedostot."); return }
    setLoading(true); setError(null)
    const form = new FormData()
    form.append("file", file)
    try {
      const { data } = await axios.post(`${API}/analyze`, form)
      setSessionId(data.session_id); setMappings(data.mappings); setFilename(data.filename)
      const { data: td } = await axios.get(`${API}/sessions/${data.session_id}/text`)
      setOriginalText(td.text)
      setPhase("review")
    } catch(e) { setError(e.response?.data?.detail || "Analyysi epaonnistui.") }
    finally { setLoading(false) }
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0])
  }, [handleFile])

  const handleRemove = async (value) => {
    await axios.post(`${API}/mapping/remove`, { session_id: sessionId, value })
    setMappings(m => m.filter(x => x.value !== value))
  }

  const handleRemoveAllOfType = async (typeCode) => {
    const toRemove = mappings.filter(m => m.type_code === typeCode)
    for (const m of toRemove) {
      await axios.post(`${API}/mapping/remove`, { session_id: sessionId, value: m.value })
    }
    setMappings(m => m.filter(x => x.type_code !== typeCode))
  }

  const handleAddManual = async () => {
    if (!manualValue.trim()) return
    try {
      const { data } = await axios.post(`${API}/mapping/add`, { session_id: sessionId, value: manualValue.trim(), pii_type: manualType })
      setMappings(m => [...m, data.mapping]); setManualValue("")
    } catch(e) { setError("Lisaaminen epaonnistui.") }
  }

  const handleAnonymize = async () => {
    setLoading(true)
    try {
      const form = new FormData(); form.append("session_id", sessionId)
      const { data } = await axios.post(`${API}/anonymize`, form)
      setAnonymizedText(data.anonymized_text); setPhase("anonymized")
    } catch(e) { setError("Anonymisointi epaonnistui.") }
    finally { setLoading(false) }
  }

  const handleDeanonymize = async () => {
    setLoading(true)
    try {
      const { data } = await axios.post(`${API}/deanonymize`, { session_id: sessionId, llm_response: llmResponse })
      setDeanonymizedText(data.deanonymized_text); setPhase("deanonymized")
    } catch(e) { setError("De-anonymisointi epaonnistui.") }
    finally { setLoading(false) }
  }

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000)
  }

  const reset = () => {
    setPhase("upload"); setSessionId(null); setMappings([]); setOriginalText("")
    setAnonymizedText(""); setLlmResponse(""); setDeanonymizedText(""); setFilename(""); setError(null)
  }

  const segments = phase === "review" ? highlightText(originalText, mappings) : []

  return (
    <div style={s.root}>
      <div style={s.bg} />
      <header style={s.header}>
        <div style={s.logo}><span style={s.logoIcon}>⬡</span><span style={s.logoText}>ANONYMISOIJA</span></div>
        <div style={s.headerRight}>
          {phase === "review" && <button style={s.primaryBtn} onClick={handleAnonymize} disabled={loading}>{loading ? "..." : "Anonymisoi"}</button>}
          {phase !== "upload" && <button style={s.ghostBtn} onClick={reset}>↩ Alusta</button>}
        </div>
      </header>
      <main style={s.main}>
        {error && <div style={s.errorBanner}>⚠ {error}<button style={s.errorClose} onClick={() => setError(null)}>✕</button></div>}

        {phase === "upload" && (
          <div style={s.uploadWrap}>
            <h1 style={s.title}>PDF- ja Word-dokumentin anonymisointi</h1>
            <p style={s.subtitle}>Poistaa henkilotiedot ennen kuin annat dokumentin tekoalylle.</p>
            <div style={{...s.dropzone,...(dragging?s.dropzoneActive:{})}} onDragOver={e=>{e.preventDefault();setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={handleDrop} onClick={()=>document.getElementById("fi").click()}>
              {loading ? <div style={s.loadingWrap}><div style={s.spinner}/><p style={s.loadingText}>Analysoidaan...</p></div> : <><div style={s.dropIcon}>📄</div><p style={s.dropText}>Vedä PDF tai Word tähän tai <span style={s.dropLink}>selaa tiedostoja</span></p><p style={s.dropHint}>Vain tekstitiedostot</p></>}
            </div>
            <input id="fi" type="file" accept=".pdf,.docx" style={{display:"none"}} onChange={e=>handleFile(e.target.files[0])} />
          </div>
        )}

        {phase === "review" && (
          <div style={s.reviewLayout}>
            <div style={s.docPanel}>
              <div style={s.panelHeader}><span style={s.panelTitle}>📄 {filename}</span><span style={s.panelHint}>{mappings.length} loydetty</span></div>
              <div style={s.docText}>
                {segments.map((seg,i) => {
                  if (!seg.highlight) return <span key={i}>{seg.text}</span>
                  const ts = getTS(seg.highlight.type_code)
                  const hov = hoveredMapping === seg.highlight.value
                  return <mark key={i} style={{background:hov?ts.accent:ts.bg,color:hov?"#000":ts.accent,borderRadius:3,padding:"1px 3px",cursor:"pointer",border:`1px solid ${ts.accent}`,transition:"all 0.15s"}} onMouseEnter={()=>setHoveredMapping(seg.highlight.value)} onMouseLeave={()=>setHoveredMapping(null)} title={ts.label}>{seg.text}</mark>
                })}
              </div>
            </div>
            <div style={s.piiPanel}>
              <div style={s.panelHeader}><span style={s.panelTitle}>Tunnistetut tiedot</span></div>
              <div style={{marginBottom:8,display:"flex",gap:6}}>
                <button style={{background:"#E8001C",color:"#fff",border:"none",borderRadius:6,padding:"8px 14px",fontSize:12,cursor:"pointer",fontFamily:"inherit"}} onClick={()=>handleRemoveAllOfType("ORG")}>Poista kaikki ORG</button>
                <button style={{...s.secondaryBtn,fontSize:10,padding:"4px 10px"}} style={{background:"#E8001C",color:"#fff",border:"none",borderRadius:6,padding:"8px 14px",fontSize:12,cursor:"pointer",fontFamily:"inherit"}} onClick={()=>handleRemoveAllOfType("HLÖ")}>Poista kaikki HLÖ</button>
              </div>
              <div style={s.cardList}>
                {mappings.map((m,i) => {
                  const ts = getTS(m.type_code)
                  const hov = hoveredMapping === m.value
                  return <div key={i} style={{...s.card,background:ts.bg,borderColor:hov?ts.accent:"#1e1e2e",boxShadow:hov?`0 0 0 1px ${ts.accent}`:"none"}} onMouseEnter={()=>setHoveredMapping(m.value)} onMouseLeave={()=>setHoveredMapping(null)}>
                    <div style={s.cardTop}><span style={{...s.typeTag,background:ts.accent}}>{ts.label}</span><button style={s.removeBtn} onClick={()=>handleRemove(m.value)}>✕</button></div>
                    <div style={s.cardValue}>{m.value}</div>
                    <div style={s.cardPlaceholder}>{m.placeholder}</div>
                    <div style={s.cardMeta}>{Math.round(m.confidence*100)}% · {m.source}{m.is_uncertain&&<span style={s.uncertainTag}> ⚠</span>}</div>
                  </div>
                })}
              </div>
              <div style={s.manualBox}>
                <p style={s.manualTitle}>Lisaa manuaalisesti</p>
                <input style={s.manualInput} placeholder="Kirjoita arvo..." value={manualValue} onChange={e=>setManualValue(e.target.value)} onKeyDown={e=>e.key==="Enter"&&handleAddManual()} />
                <div style={s.manualRow}>
                  <select style={s.manualSelect} value={manualType} onChange={e=>setManualType(e.target.value)}>
                    <option value="CUSTOM">Muu</option><option value="PERSON">Henkilo</option><option value="ORGANIZATION">Organisaatio</option><option value="LOCATION">Sijainti</option>
                  </select>
                  <button style={{background:"#E8001C",color:"#fff",border:"none",borderRadius:6,padding:"8px 14px",fontSize:12,cursor:"pointer",fontFamily:"inherit"}} onClick={handleAddManual}>Lisaa</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {phase === "anonymized" && (
          <div style={s.textWrap}>
            <div style={s.textHeader}><h2 style={s.sectionTitle}>Anonymisoitu teksti</h2><button style={s.secondaryBtn} onClick={()=>handleCopy(anonymizedText)}>{copied?"✓ Kopioitu!":"📋 Kopioi"}</button></div>
            <p style={s.instructions}>Kopioi teksti ja anna se tekoalylle. Liita vastaus alle.</p>
            <textarea style={s.textArea} value={anonymizedText} readOnly />
            <div style={s.llmSection}>
              <h3 style={s.manualTitle}>Tekoalyn vastaus</h3>
              <textarea style={{...s.textArea,minHeight:150}} placeholder="Liita tekoalyn vastaus tahan..." value={llmResponse} onChange={e=>setLlmResponse(e.target.value)} />
              <button style={{...s.primaryBtn,marginTop:12}} onClick={handleDeanonymize} disabled={!llmResponse.trim()||loading}>{loading?"...":"De-anonymisoi"}</button>
            </div>
          </div>
        )}

        {phase === "deanonymized" && (
          <div style={s.textWrap}>
            <div style={s.textHeader}><h2 style={s.sectionTitle}>✓ De-anonymisoitu vastaus</h2><button style={s.secondaryBtn} onClick={()=>handleCopy(deanonymizedText)}>📋 Kopioi</button></div>
            <p style={s.instructions}>Alkuperaiset henkilotiedot on palautettu tekoalyn vastaukseen.</p>
            <textarea style={s.textArea} value={deanonymizedText} readOnly />
            <button style={{...s.primaryBtn,marginTop:16}} onClick={reset}>↩ Uusi dokumentti</button>
          </div>
        )}
      </main>
      <footer style={s.footer}>
        <span style={s.footerSlogan}>Maalaisjärjellä ajateltuja IT-ratkaisuja</span>
        <a href="https://jhcomputer.fi" target="_blank">
          <img src="/src/assets/logo.png" alt="Data Group JH Computer" style={{height:36}} />
        </a>
        <span style={s.footerText}>Powered by <a href="https://jhcomputer.fi" target="_blank" style={s.footerLink}>Data Group – JH Computer</a></span>
      </footer>
    </div>
  )
}

const s = {
  root:{minHeight:"100vh",background:"#0a0a0f",color:"#e8e8f0",fontFamily:"'DM Mono','Courier New',monospace",position:"relative"},
  bg:{position:"fixed",inset:0,background:"radial-gradient(ellipse at 20% 50%, #0d1f3c 0%, transparent 60%), radial-gradient(ellipse at 80% 20%, #1a0a2e 0%, transparent 50%)",pointerEvents:"none",zIndex:0},
  header:{position:"relative",zIndex:10,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"16px 32px",borderBottom:"1px solid #1e1e2e"},
  logo:{display:"flex",alignItems:"center",gap:10},
  logoIcon:{fontSize:20,color:"#E8001C"},
  logoText:{fontSize:12,fontWeight:700,letterSpacing:"0.2em",color:"#E8001C"},
  headerRight:{display:"flex",gap:10,alignItems:"center"},
  main:{position:"relative",zIndex:10,maxWidth:1200,margin:"0 auto",padding:"32px 24px"},
  errorBanner:{background:"#2d0a0a",border:"1px solid #7f1d1d",color:"#fca5a5",padding:"10px 16px",borderRadius:6,marginBottom:20,display:"flex",justifyContent:"space-between",alignItems:"center",fontSize:13},
  errorClose:{background:"none",border:"none",color:"#fca5a5",cursor:"pointer"},
  uploadWrap:{textAlign:"center",paddingTop:60,maxWidth:600,margin:"0 auto"},
  title:{fontSize:38,fontWeight:700,lineHeight:1.2,marginBottom:16},
  subtitle:{color:"#888",fontSize:15,marginBottom:48},
  dropzone:{border:"2px dashed #2a2a3e",borderRadius:12,padding:"60px 40px",cursor:"pointer",transition:"all 0.2s",background:"#0d0d1a"},
  dropzoneActive:{borderColor:"#E8001C",background:"#0a1628"},
  dropIcon:{fontSize:48,marginBottom:16},
  dropText:{fontSize:16,marginBottom:8},
  dropLink:{color:"#E8001C"},
  dropHint:{color:"#555",fontSize:12},
  loadingWrap:{display:"flex",flexDirection:"column",alignItems:"center",gap:16},
  spinner:{width:32,height:32,border:"3px solid #1e1e2e",borderTop:"3px solid #E8001C",borderRadius:"50%",animation:"spin 0.8s linear infinite"},
  loadingText:{color:"#888",fontSize:13},
  reviewLayout:{display:"grid",gridTemplateColumns:"1fr 300px",gap:20,alignItems:"start"},
  docPanel:{background:"#0d0d1a",border:"1px solid #1e1e2e",borderRadius:10,overflow:"hidden"},
  piiPanel:{display:"flex",flexDirection:"column",gap:10},
  panelHeader:{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"10px 16px",borderBottom:"1px solid #1e1e2e",background:"#0a0a12"},
  panelTitle:{fontSize:11,fontWeight:700,letterSpacing:"0.1em",color:"#888"},
  panelHint:{fontSize:10,color:"#555"},
  docText:{padding:20,fontSize:12,lineHeight:2,whiteSpace:"pre-wrap",maxHeight:"75vh",overflowY:"auto",color:"#ccc"},
  cardList:{display:"flex",flexDirection:"column",gap:6,maxHeight:"55vh",overflowY:"auto"},
  card:{border:"1px solid",borderRadius:8,padding:"10px 12px",transition:"all 0.15s"},
  cardTop:{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6},
  typeTag:{fontSize:9,fontWeight:700,padding:"2px 7px",borderRadius:20,color:"#fff",letterSpacing:"0.1em"},
  removeBtn:{background:"none",border:"none",color:"#555",cursor:"pointer",fontSize:11},
  cardValue:{fontSize:13,fontWeight:600,marginBottom:3,wordBreak:"break-word"},
  cardPlaceholder:{fontSize:10,color:"#666",fontFamily:"monospace",marginBottom:4},
  cardMeta:{fontSize:10,color:"#555"},
  uncertainTag:{color:"#f59e0b"},
  manualBox:{background:"#0d0d1a",border:"1px solid #1e1e2e",borderRadius:8,padding:14},
  manualTitle:{fontSize:11,fontWeight:700,color:"#666",marginBottom:10,letterSpacing:"0.1em"},
  manualInput:{width:"100%",background:"#0a0a0f",border:"1px solid #2a2a3e",borderRadius:6,padding:"7px 10px",color:"#e8e8f0",fontFamily:"inherit",fontSize:12,outline:"none",boxSizing:"border-box",marginBottom:8},
  manualRow:{display:"flex",gap:8},
  manualSelect:{flex:1,background:"#0a0a0f",border:"1px solid #2a2a3e",borderRadius:6,padding:"6px 8px",color:"#e8e8f0",fontFamily:"inherit",fontSize:11,outline:"none"},
  primaryBtn:{background:"#E8001C",color:"#0a0a0f",border:"none",borderRadius:6,padding:"9px 18px",fontWeight:700,fontSize:12,cursor:"pointer",fontFamily:"inherit",whiteSpace:"nowrap"},
  secondaryBtn:{background:"transparent",color:"#E8001C",border:"1px solid #E8001C",borderRadius:6,padding:"7px 14px",fontSize:11,cursor:"pointer",fontFamily:"inherit"},
  ghostBtn:{background:"transparent",color:"#666",border:"1px solid #333",borderRadius:6,padding:"7px 14px",fontSize:11,cursor:"pointer",fontFamily:"inherit"},
  sectionTitle:{fontSize:22,fontWeight:700,marginBottom:4},
  textWrap:{maxWidth:800},
  textHeader:{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12},
  instructions:{color:"#888",fontSize:13,marginBottom:16,lineHeight:1.6},
  textArea:{width:"100%",minHeight:300,background:"#0d0d1a",border:"1px solid #1e1e2e",borderRadius:8,padding:16,color:"#e8e8f0",fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.7,resize:"vertical",outline:"none",boxSizing:"border-box"},
  llmSection:{marginTop:32,paddingTop:32,borderTop:"1px solid #1e1e2e"},
  footer:{position:"relative",zIndex:10,borderTop:"1px solid #1e1e2e",padding:"16px 32px",display:"flex",justifyContent:"space-between",alignItems:"center",marginTop:40},
  footerText:{fontSize:11,color:"#555"},
  footerLink:{color:"#E8001C",textDecoration:"none",fontSize:11},
  footerSlogan:{fontSize:11,color:"#444",fontStyle:"italic"},
}
