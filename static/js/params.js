// ── Chemsbury Parameter Definitions ────────────────────────────────────────
// Dynamically loaded from server; PARAM_DEFS populated by loadParamDefs()

let PARAM_DEFS = [];

async function loadParamDefs() {
  try {
    const data = await API.get('/api/parameters/public');
    if (!data || !data.length) throw new Error('Empty response');
    PARAM_DEFS = data.map(p => ({
      key:      p.parameter_name,
      label:    p.parameter_name.charAt(0).toUpperCase() + p.parameter_name.slice(1).replace(/_/g,' '),
      unit:     p.unit || '',
      warnHigh: p.permissible_limit,
      warnLow:  p.lo_is_bad ? p.lo_limit : null,
    }));
  } catch (e) {
    console.warn('Using fallback PARAM_DEFS:', e.message);
    // Fallback static definitions
    PARAM_DEFS = [
      { key:'ph',         label:'pH',           unit:'',          warnHigh:8.5,  warnLow:6.5  },
      { key:'turbidity',  label:'Turbidity',    unit:'NTU',       warnHigh:5,    warnLow:null },
      { key:'tds',        label:'TDS',          unit:'mg/L',      warnHigh:500,  warnLow:null },
      { key:'hardness',   label:'Hardness',     unit:'mg/L',      warnHigh:300,  warnLow:null },
      { key:'iron',       label:'Iron',         unit:'mg/L',      warnHigh:0.3,  warnLow:null },
      { key:'chloride',   label:'Chloride',     unit:'mg/L',      warnHigh:250,  warnLow:null },
      { key:'fluoride',   label:'Fluoride',     unit:'mg/L',      warnHigh:1.5,  warnLow:null },
      { key:'nitrate',    label:'Nitrate',      unit:'mg/L',      warnHigh:45,   warnLow:null },
      { key:'manganese',  label:'Manganese',    unit:'mg/L',      warnHigh:0.1,  warnLow:null },
      { key:'alkalinity', label:'Alkalinity',   unit:'mg/L',      warnHigh:200,  warnLow:null },
      { key:'sulphate',   label:'Sulphate',     unit:'mg/L',      warnHigh:200,  warnLow:null },
      { key:'calcium',    label:'Calcium',      unit:'mg/L',      warnHigh:75,   warnLow:null },
      { key:'magnesium',  label:'Magnesium',    unit:'mg/L',      warnHigh:30,   warnLow:null },
      { key:'copper',     label:'Copper',       unit:'mg/L',      warnHigh:0.05, warnLow:null },
      { key:'arsenic',    label:'Arsenic',      unit:'mg/L',      warnHigh:0.01, warnLow:null },
      { key:'lead',       label:'Lead',         unit:'mg/L',      warnHigh:0.01, warnLow:null },
      { key:'coliform',   label:'Total Coliform',unit:'MPN/100mL',warnHigh:0,    warnLow:null },
      { key:'ecoli',      label:'E. Coli',      unit:'MPN/100mL', warnHigh:0,    warnLow:null },
      { key:'ammonia',    label:'Ammonia',      unit:'mg/L',      warnHigh:0.5,  warnLow:null },
      { key:'nitrite',    label:'Nitrite',      unit:'mg/L',      warnHigh:0.02, warnLow:null },
      { key:'colour',     label:'Colour',       unit:'Hazen',     warnHigh:15,   warnLow:null },
      { key:'tss',        label:'TSS',          unit:'mg/L',      warnHigh:10,   warnLow:null },
      { key:'bod',        label:'BOD',          unit:'mg/L',      warnHigh:2,    warnLow:null },
      { key:'h2s',        label:'H₂S / Sulphide',unit:'mg/L',    warnHigh:0.05, warnLow:null },
    ];
  }
}

// ── Filter Types ─────────────────────────────────────────────────────────────
// Each filter has an `addresses` array for individual parameters
// AND a `combo` function for combination logic
const FILTER_TYPES = [
  {
    id: 'multimedia',
    icon: '🌊',
    name: 'Multi-Media Filter (MMF)',
    desc: 'Removes suspended solids, turbidity, and colour. Ideal as a primary treatment stage before RO or softeners.',
    media: ['Anthracite', 'Filter Sand', 'Gravel Support'],
    addresses: ['turbidity', 'tss', 'colour'],
    contactTime: 12,
    combo: params => {
      // Recommend when turbidity OR TSS is elevated
      return (params.turbidity > 2) || (params.tss > 5) || (params.colour > 5);
    },
    unitPrices: {
      'Anthracite':      { price: 2800, unit: 'kg' },
      'Filter Sand':     { price:  450, unit: 'kg' },
      'Gravel Support':  { price:  280, unit: 'kg' },
    },
    installCost: 12000,
  },
  {
    id: 'iron_manganese',
    icon: '🔩',
    name: 'Iron & Manganese Filter',
    desc: 'Oxidises and captures dissolved iron and manganese, preventing staining and metallic taste.',
    media: ['Greensand Plus', 'Filter Sand', 'Gravel Support'],
    addresses: ['iron', 'manganese', 'h2s'],
    contactTime: 15,
    combo: params => {
      return (params.iron > 0.1) || (params.manganese > 0.05) || (params.h2s > 0.01);
    },
    unitPrices: {
      'Greensand Plus': { price: 4200, unit: 'kg' },
      'Filter Sand':    { price:  450, unit: 'kg' },
      'Gravel Support': { price:  280, unit: 'kg' },
    },
    installCost: 15000,
  },
  {
    id: 'softener',
    icon: '💧',
    name: 'Water Softener (Ion Exchange)',
    desc: 'Removes calcium and magnesium hardness through ion exchange with sodium. Protects appliances and pipework.',
    media: ['Cation Resin', 'Anti-scalant Resin', 'Gravel Support'],
    addresses: ['hardness', 'calcium', 'magnesium'],
    contactTime: 10,
    combo: params => {
      return (params.hardness > 150) || (params.calcium > 50) || (params.magnesium > 20);
    },
    unitPrices: {
      'Cation Resin':         { price: 6500, unit: 'kg' },
      'Anti-scalant Resin':   { price: 7200, unit: 'kg' },
      'Gravel Support':       { price:  280, unit: 'kg' },
    },
    installCost: 18000,
  },
  {
    id: 'activated_carbon',
    icon: '⚫',
    name: 'Activated Carbon Filter (ACF)',
    desc: 'Adsorbs chlorine, organic compounds, pesticides, and taste/odour problems.',
    media: ['Granular Activated Carbon', 'Activated Carbon Sand', 'Gravel Support'],
    addresses: ['chloride', 'colour', 'tds'],
    contactTime: 10,
    combo: params => {
      return (params.chloride > 100) || (params.colour > 5) || (params.tds > 300 && params.tds <= 500);
    },
    unitPrices: {
      'Granular Activated Carbon': { price: 5500, unit: 'kg' },
      'Activated Carbon Sand':     { price: 1800, unit: 'kg' },
      'Gravel Support':            { price:  280, unit: 'kg' },
    },
    installCost: 14000,
  },
  {
    id: 'defluoridation',
    icon: '🦷',
    name: 'Defluoridation Filter',
    desc: 'Removes excess fluoride using activated alumina or bone char media, critical in high-fluoride groundwater zones.',
    media: ['Activated Alumina', 'Filter Sand', 'Gravel Support'],
    addresses: ['fluoride', 'arsenic', 'aluminium'],
    contactTime: 18,
    combo: params => {
      return (params.fluoride > 1.0) || (params.arsenic > 0.005);
    },
    unitPrices: {
      'Activated Alumina': { price: 3800, unit: 'kg' },
      'Filter Sand':       { price:  450, unit: 'kg' },
      'Gravel Support':    { price:  280, unit: 'kg' },
    },
    installCost: 16000,
  },
  {
    id: 'ro',
    icon: '🔬',
    name: 'Reverse Osmosis (RO) System',
    desc: 'Removes up to 99% of dissolved salts, heavy metals, nitrates, bacteria and viruses. For high-TDS or contaminated water.',
    media: ['RO Membrane (TFC)', 'Activated Carbon Pre-filter', 'Sediment Pre-filter 5μ'],
    addresses: ['tds', 'nitrate', 'lead', 'arsenic', 'coliform', 'ecoli'],
    contactTime: 8,
    combo: params => {
      return (params.tds > 500) || (params.nitrate > 30) ||
             (params.lead > 0.005) || (params.arsenic > 0.005) ||
             ((params.coliform || 0) > 0) || ((params.ecoli || 0) > 0);
    },
    unitPrices: {
      'RO Membrane (TFC)':           { price: 8500,  unit: 'pc' },
      'Activated Carbon Pre-filter': { price: 1200,  unit: 'pc' },
      'Sediment Pre-filter 5μ':      { price:  650,  unit: 'pc' },
    },
    installCost: 25000,
  },
];

// ── Vessel Sizes ──────────────────────────────────────────────────────────────
const VESSEL_SIZES = [
  { model: 'CS-0844', dia: 8,  height: 44, maxVol: 40,  maxFlow: 0.5  },
  { model: 'CS-1044', dia: 10, height: 44, maxVol: 65,  maxFlow: 0.8  },
  { model: 'CS-1252', dia: 12, height: 52, maxVol: 120, maxFlow: 1.5  },
  { model: 'CS-1465', dia: 14, height: 65, maxVol: 200, maxFlow: 2.5  },
  { model: 'CS-1665', dia: 16, height: 65, maxVol: 280, maxFlow: 3.5  },
  { model: 'CS-1865', dia: 18, height: 65, maxVol: 360, maxFlow: 4.5  },
  { model: 'CS-2162', dia: 21, height: 62, maxVol: 500, maxFlow: 6.0  },
  { model: 'CS-2472', dia: 24, height: 72, maxVol: 800, maxFlow: 10.0 },
];

// ── Media colors for vessel diagram ──────────────────────────────────────────
const MEDIA_COLORS = {
  'Anthracite':                   '#4a5568',
  'Filter Sand':                  '#d4a94e',
  'Gravel Support':                '#8b7355',
  'Greensand Plus':               '#2d6a4f',
  'Cation Resin':                 '#e07b54',
  'Anti-scalant Resin':           '#c65d3a',
  'Granular Activated Carbon':    '#1a1a2e',
  'Activated Carbon Sand':        '#2d3748',
  'Activated Alumina':            '#6b8cba',
  'RO Membrane (TFC)':            '#3ecfcf',
  'Activated Carbon Pre-filter':  '#2d3748',
  'Sediment Pre-filter 5μ':       '#a0aec0',
  'Bone Char':                    '#e2d5c3',
};

// ── Price list (component prices in INR) ─────────────────────────────────────
const VESSEL_PRICES = {
  'CS-0844': 8500,
  'CS-1044': 11000,
  'CS-1252': 15500,
  'CS-1465': 22000,
  'CS-1665': 28500,
  'CS-1865': 36000,
  'CS-2162': 48000,
  'CS-2472': 68000,
};

// ── Filter recommendation logic ──────────────────────────────────────────────
// Returns { recommended: [{filterId, reasons}], all: [filterId] }
function getFilterRecommendations(params) {
  const recommended = [];

  FILTER_TYPES.forEach(f => {
    const reasons = [];

    // Check combination condition
    if (f.combo && f.combo(params)) {
      f.addresses.forEach(key => {
        const def = PARAM_DEFS.find(p => p.key === key);
        if (!def) return;
        const v = params[key];
        if (v !== undefined && def.warnHigh !== null && v > def.warnHigh) {
          reasons.push(`${def.label} is ${v} ${def.unit} (limit: ${def.warnHigh})`);
        }
      });
      if (reasons.length === 0) reasons.push('One or more parameters require this treatment');
      recommended.push({ filterId: f.id, reasons });
    }
  });

  return recommended;
}
