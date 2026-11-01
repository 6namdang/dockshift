/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

export interface ComponentVisibility {
  showProtein: boolean;
  showRna: boolean;
  showDna: boolean;
  showInhibitor: boolean;
}

export type SelectedComponentType = 'all' | 'tert' | 'terc' | 'dna' | 'inhibitor' | 'pocket' | 'protein' | 'rna';

export interface MolecularSubunit {
  id: string;
  name: string;
  type: 'protein' | 'rna' | 'dna' | 'inhibitor';
  chain: string;
  authChain: string;
  resn?: string;
  color: string;
  description: string;
  role: string;
  lengthOrAtoms: string;
  keyFeatures: string[];
}

export interface Protein {
  id: string;
  name: string;
  systemTitle: string;
  pdbId: string;
  structureUrl: string;
  fallbackUrl?: string;
  description: string;
  biologicalRole: string;
  cancerRelevance: string;
  organism: string;
  resolution: string;
  experimentalMethod: string;
  citation: string;
  doi: string;
  subunits: MolecularSubunit[];
  experimentalInhibitor: {
    name: string;
    code: string;
    chemicalName: string;
    chemicalFormula: string;
    molecularWeight: number;
    smiles: string;
    bindingPocket: string;
    mechanism: string;
    keyContactResidues: { resi: number; resn: string; role: string; chain: string }[];
    centerCoords: [number, number, number];
  };
}

export interface QSARPrediction {
  predicted_pic50: number;
  predicted_ic50_nm: number;
  measured_pic50?: number | null;
  measured_count?: number;
  max_tanimoto: number;
  domain: 'in' | 'out';
  in_training_set?: boolean;
  pubchem_cid?: number;
  smiles?: string;
}

export interface PhysicochemicalProfile {
  molecular_weight?: number;
  clogp?: number;
  hbd?: number;
  hba?: number;
  tpsa?: number;
  rotatable_bonds?: number;
  qed?: number;
  lipinski_violations?: number;
  lipinski_pass?: boolean;
  veber_pass?: boolean;
}

export interface Ligand {
  id: string;
  name: string;
  rank?: number;
  selected?: boolean;
  smiles?: string;
  structureUrl?: string;
  chemicalFormula?: string;
  molecularWeight?: number;
  description?: string;
  tag: string;
  targetSite: string;
  note?: string;
  prediction?: QSARPrediction;
  profile?: PhysicochemicalProfile;
}

export type DockingStatus = 'awaiting_results' | 'pose_not_available' | 'docked' | 'failed' | 'simulating';

export interface DockingInteraction {
  type: 'hydrogen_bond' | 'pi_stacking' | 'hydrophobic' | 'salt_bridge';
  residue: string;
  distance: string;
}

export interface DockingResult {
  id: string;
  proteinId: string;
  ligandId: string;
  score: number | null;
  scoringMethod?: string;
  poseUrl?: string;
  interactions?: DockingInteraction[];
  status: DockingStatus;
  statusMessage: string;
  dockingBox?: {
    center: [number, number, number];
    size: [number, number, number];
  };
  exhaustiveness?: number;
  notes?: string;
}

export type DiscoveryCategory = 'SUPPORT' | 'CHALLENGE' | 'SURPRISE' | 'SPACE';

export interface DiscoveryPrompt {
  id: string;
  category: DiscoveryCategory;
  title: string;
  question: string;
  context: string;
  reflectionQuestion: string;
  suggestedAction: string;
  suggestedNote: string;
}

export interface GuidedChallenge {
  id: string;
  title: string;
  level: 'Beginner' | 'Intermediate' | 'Advanced';
  question: string;
  hint: string;
  explanation: string;
  focusTarget: SelectedComponentType;
  actionLabel: string;
}

export interface ResearchNote {
  id: string;
  title: string;
  category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment';
  content: string;
  targetId: string;
  candidateId?: string;
  timestamp: string;
  tags: string[];
}

export interface LiteraturePaper {
  id: string;
  title: string;
  url?: string;
  source: 'pubmed' | 'biorxiv' | 'chemrxiv' | 'patents' | 'pubchem' | string;
  published_date?: string;
  venue?: string;
  confidence?: number;
  doi?: string;
  authors?: string[];
  abstract?: string;
}
