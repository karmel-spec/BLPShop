// Drafts a client progress-update email in Brigham's voice from shop evidence.
// Admin-gated: the caller must present a valid Google ID token for an admin
// account. Requires ANTHROPIC_API_KEY in Netlify env vars — until it is set,
// returns 503 and the manager UI falls back to a local template draft.
const GOOGLE_CLIENT_ID =
  '118454775893-17u7t3glh8eu4kffhe7b42jl71apre4f.apps.googleusercontent.com';
const ADMIN_DOMAIN = 'brighamlarsonpianos.com';
const ADMIN_EMAILS = ['brighamlarson@gmail.com', 'brighamlarsonpianos@gmail.com', 'pianoshop.blp@gmail.com'];

// Style examples for the voice packet. Placeholder until the extraction
// session pulls real samples from Brigham's Sent mail — replace SAMPLES then.
const VOICE = `You write client progress-update emails as Brigham Larson, owner of Brigham
Larson Pianos in Utah. Voice: warm, personal, enthusiastic about craftsmanship,
plain English (technical terms briefly explained), genuinely excited about the
client's specific piano. Structure: greet by first name; lead with the most
exciting progress; describe recent work concretely (name the parts and steps);
say what happens next; invite questions; warm sign-off as Brigham. Keep it
150-250 words. Never invent work that is not in the evidence. If progress was
slow this period, be honest and kind about it and emphasize what is coming.
Do not mention internal codes (PRSB, CAP, DHRT) — translate them:
PRSB = structural work on the soundboard, ribs and bridges;
CAP = cleaning and rebuilding the action; DHRT = dampers, hammers,
regulation and pedal trapwork; QC = final quality inspection.`;

async function verifyAdmin(idToken) {
  if (!idToken) return null;
  const r = await fetch('https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(idToken));
  if (!r.ok) return null;
  const info = await r.json();
  if (info.aud !== GOOGLE_CLIENT_ID) return null;
  if (info.email_verified !== 'true' && info.email_verified !== true) return null;
  const email = String(info.email || '').toLowerCase();
  if (email.endsWith('@' + ADMIN_DOMAIN) || ADMIN_EMAILS.includes(email)) return email;
  return null;
}

exports.handler = async (event) => {
  const json = (code, body) => ({ statusCode: code, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (event.httpMethod !== 'POST') return json(405, { error: 'POST required' });

  let req;
  try { req = JSON.parse(event.body || '{}'); } catch (e) { return json(400, { error: 'bad json' }); }

  const admin = await verifyAdmin(req.idToken);
  if (!admin) return json(401, { error: 'admin sign-in required' });

  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return json(503, { error: 'no-key' });

  const p = req.piano || {};
  const evidence = (req.evidence || []).slice(0, 30);
  const phases = req.phases || {};
  const user = `Draft the update email now.

PIANO: ${p.summary || p.label || ''} (serial ${p.serial || '?'})
CLIENT: ${p.ownerName || 'the owner'}
LAST UPDATE SENT: ${req.lastUpdate || 'unknown / first update'}

PHASE SIGN-OFFS FROM THE SHOP LOG:
${Object.entries(phases).map(([k, v]) => `- ${k}: ${v}`).join('\n') || '(none recorded)'}

TECHNICIAN REPORT EXCERPTS SINCE THE LAST UPDATE (newest last):
${evidence.map(e => `[${e.date} — ${e.tech}] ${e.text}`).join('\n') || '(no report mentions this period)'}

Respond with JSON only: {"subject": "...", "body": "..."} — body is plain text
with real line breaks, no markdown.`;

  try {
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'claude-sonnet-5',
        max_tokens: 1200,
        system: VOICE,
        messages: [{ role: 'user', content: user }],
      }),
    });
    const out = await r.json();
    if (!r.ok) return json(502, { error: out.error && out.error.message || 'api error' });
    const text = (out.content || []).map(c => c.text || '').join('');
    const m = text.match(/\{[\s\S]*\}/);
    const draft = m ? JSON.parse(m[0]) : { subject: 'Progress update on your piano', body: text };
    return json(200, { ok: true, subject: draft.subject, body: draft.body, by: admin });
  } catch (e) {
    return json(502, { error: String(e.message || e) });
  }
};
