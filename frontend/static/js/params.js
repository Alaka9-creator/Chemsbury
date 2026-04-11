/**
 * params.js — water parameter definitions, filter types, vessel sizes.
 * Loads limits dynamically from the server; falls back to hardcoded IS:10500.
 */

/* ── Hardcoded fallback (IS:10500) ── */
const _PARAM_DEFS_FALLBACK = [
  { key:'ph',         label:'pH',                    unit:'',          warnHigh:8.5,   warnLow:6.5  },
  { key:'tds',        label:'TDS',                   unit:'mg/L',      warnHigh:500                 },
  { key:'turbidity',  label:'Turbidity',              unit:'NTU',       warnHigh:5                   },
  { key:'hardness',   label:'Hardness',               unit:'mg/L',      warnHigh:300                 },
  { key:'iron',       label:'Iron (Fe)',              unit:'mg/L',      warnHigh:0.3                 },
  { key:'chloride',   label:'Chloride',               unit:'mg/L',      warnHigh:250                 },
  { key:'fluoride',   label:'Fluoride',               unit:'mg/L',      warnHigh:1.5                 },
  { key:'nitrate',    label:'Nitrate',                unit:'mg/L',      warnHigh:45                  },
  { key:'manganese',  label:'Manganese',              unit:'mg/L',      warnHigh:0.1                 },
  { key:'alkalinity', label:'Alkalinity',             unit:'mg/L',      warnHigh:200                 },
  { key:'sulphate',   label:'Sulphate',               unit:'mg/L',      warnHigh:200                 },
  { key:'calcium',    label:'Calcium',                unit:'mg/L',      warnHigh:75                  },
  { key:'magnesium',  label:'Magnesium',              unit:'mg/L',      warnHigh:30                  },
  { key:'copper',     label:'Copper',                 unit:'mg/L',      warnHigh:0.05                },
  { key:'zinc',       label:'Zinc',                   unit:'mg/L',      warnHigh:5                   },
  { key:'arsenic',    label:'Arsenic',                unit:'mg/L',      warnHigh:0.01                },
  { key:'lead',       label:'Lead',                   unit:'mg/L',      warnHigh:0.01                },
  { key:'chromium',   label:'Chromium',               unit:'mg/L',      warnHigh:0.05                },
  { key:'aluminium',  label:'Aluminium',              unit:'mg/L',      warnHigh:0.1                 },
  { key:'ammonia',    label:'Ammonia',                unit:'mg/L',      warnHigh:0.5                 },
  { key:'h2s',        label:'H₂S',                   unit:'mg/L',      warnHigh:0.05                },
  { key:'boron',      label:'Boron',                  unit:'mg/L',      warnHigh:1.0                 },
  { key:'nitrite',    label:'Nitrite',                unit:'mg/L',      warnHigh:0.02                },
  { key:'phenol',     label:'Phenolic Compounds',     unit:'mg/L',      warnHigh:0.001               },
  { key:'coliform',   label:'Coliform',               unit:'MPN/100mL', warnHigh:0                   },
  { key:'ecoli',      label:'E. coli',                unit:'MPN/100mL', warnHigh:0                   },
  { key:'tss',        label:'TSS',                    unit:'mg/L',      warnHigh:10                  },
  { key:'bod',        label:'BOD',                    unit:'mg/L',      warnHigh:2                   },
  { key:'cod',        label:'COD',                    unit:'mg/L',      warnHigh:10                  },
  { key:'colour',     label:'Colour',                 unit:'Hazen',     warnHigh:15                  },
];

/* Live param defs — populated by loadParamDefs() */
let PARAM_DEFS = [..._PARAM_DEFS_FALLBACK];

/**
 * Fetch active parameter limits from the server and rebuild PARAM_DEFS.
 * Falls back silently to hardcoded values if the request fails.
 */
async function loadParamDefs() {
  try {
    const data = await fetch('/api/parameters/public').then(r => r.json());
    if (!Array.isArray(data) || data.length === 0) return;

    PARAM_DEFS = data.map(p => ({
      key:      p.parameter_name,
      label:    p.parameter_name.charAt(0).toUpperCase() +
                p.parameter_name.slice(1).replace(/_/g, ' '),
      unit:     p.unit || '',
      warnHigh: p.permissible_limit ?? undefined,
      warnLow:  p.lo_is_bad         ? (p.lo_limit ?? undefined) : undefined,
    }));
  } catch (e) {
    console.warn('Could not load live param defs, using fallback:', e.message);
  }
}

/* ── Filter types ── */
const FILTER_TYPES = [
  {
    id: 'sediment', icon: '🪨', name: 'Sediment Filter',
    desc: 'Removes suspended particles, dirt, sand and silt. Ideal for high turbidity water.',
    media: ['Multi-Grade Sand','Anthracite','Gravel Support'],
    addresses: ['turbidity'], contactTime: 10,
  },
  {
    id: 'iron_removal', icon: '⚙️', name: 'Iron Removal Filter',
    desc: 'Oxidises and filters dissolved iron and manganese from borewell water.',
    media: ['Manganese Dioxide','Birm','Gravel Base'],
    addresses: ['iron','manganese'], contactTime: 15,
  },
  {
    id: 'activated_carbon', icon: '🖤', name: 'Activated Carbon Filter',
    desc: 'Removes chlorine, chloramines, H₂S odour and organic compounds. Improves taste.',
    media: ['Catalytic Carbon','Activated Carbon','Gravel Support'],
    addresses: ['h2s','chloride'], contactTime: 12,
  },
  {
    id: 'softener', icon: '🔵', name: 'Water Softener',
    desc: 'Ion exchange removes calcium and magnesium to reduce hardness.',
    media: ['Cation Exchange Resin','Brine / NaCl','Gravel Base'],
    addresses: ['hardness'], contactTime: 10,
  },
  {
    id: 'ro', icon: '💎', name: 'RO Membrane System',
    desc: 'Reverse osmosis for high TDS and broad-spectrum contaminant removal.',
    media: ['TFC RO Membrane','Pre-Carbon','Post-Carbon','Antiscalant'],
    addresses: ['tds','fluoride','nitrate'], contactTime: 0,
  },
  {
    id: 'multimedia', icon: '🔩', name: 'Multi-Media Filter',
    desc: 'Layered filtration combining multiple media to address several parameters simultaneously.',
    media: ['Anthracite','Sand','Garnet','Gravel'],
    addresses: ['turbidity','iron','h2s'], contactTime: 15,
  },
];

/* ── Vessel sizes ── */
const VESSEL_SIZES = [
  { model:'0844', dia:8,  height:44, maxVol:20  },
  { model:'1054', dia:10, height:54, maxVol:40  },
  { model:'1252', dia:12, height:52, maxVol:60  },
  { model:'1354', dia:13, height:54, maxVol:80  },
  { model:'1465', dia:14, height:65, maxVol:120 },
  { model:'1665', dia:16, height:65, maxVol:160 },
  { model:'2162', dia:21, height:62, maxVol:250 },
];

/* ── Media colours ── */
const MEDIA_COLORS = {
  'Multi-Grade Sand':        '#c8a96e',
  'Anthracite':              '#3a3f50',
  'Gravel Support':          '#8a7a60',
  'Gravel Base':             '#8a7a60',
  'Manganese Dioxide':       '#6d4c2a',
  'Birm':                    '#855e3a',
  'Catalytic Carbon':        '#1e2330',
  'Activated Carbon':        '#252b3b',
  'Cation Exchange Resin':   '#c9830a',
  'Brine / NaCl':            '#e0d7c8',
  'TFC RO Membrane':         '#3a78b0',
  'Pre-Carbon':              '#2a3545',
  'Post-Carbon':             '#2a3545',
  'Antiscalant':             '#4a8fa8',
  'Garnet':                  '#7a2a2a',
  'Sand':                    '#c8a96e',
  'Gravel':                  '#8a7a60',
};
