/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import {
  ExternalLink,
  Flame,
  CheckCircle2,
  Crosshair,
  Sparkles
} from 'lucide-react';
import { DockShiftIcon } from './DockShiftLogo';
import { Protein } from '../types/docking';

interface StructureInfoBarProps {
  protein: Protein;
  onFocusInhibitor?: () => void;
  className?: string;
}

export const StructureInfoBar: React.FC<StructureInfoBarProps> = ({
  protein,
  onFocusInhibitor,
  className = ''
}) => {
  return (
    <div
      className={`px-4 py-2 bg-[#0B1118]/90 backdrop-blur-md border-b border-[#202F3C] flex flex-wrap items-center justify-between gap-3 text-xs select-none ${className}`}
    >
      {/* Left: Primary Metadata Items */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        {/* Item 1: Human Telomerase */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-[#18232D] border border-[#202F3C] text-[#59C9C0] font-semibold">
          <DockShiftIcon size={16} variant="transparent" dotColor="#59C9C0" />
          <span>Human Telomerase</span>
        </div>

        {/* Item 2: PDB: 9Q14 with outbound link */}
        <a
          href={`https://www.rcsb.org/structure/${protein.pdbId || '9Q14'}`}
          target="_blank"
          rel="noreferrer"
          title="View experimental record on RCSB Protein Data Bank"
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#18232D] border border-[#202F3C] hover:border-[#59C9C0]/50 text-[#E9F0F3] transition group font-mono text-[11px]"
        >
          <span className="text-[#90A4AF]">PDB:</span>
          <span className="font-bold text-[#59C9C0] group-hover:underline">9Q14</span>
          <ExternalLink className="w-3 h-3 text-[#90A4AF] group-hover:text-[#59C9C0]" />
        </a>

        {/* Item 3: Catalytic Core Complexed */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#18232D] border border-[#202F3C] text-[#90A4AF] text-[11px]">
          <CheckCircle2 className="w-3 h-3 text-[#59C9C0]" />
          <span>Catalytic Core ({protein.resolution || '3.00 Å'})</span>
        </div>

        {/* Item 4: Target: BIBR1532 Inhibitor Site */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#18232D] border border-[#202F3C] text-[#E9A76A] font-medium text-[11px]">
          <Flame className="w-3.5 h-3.5 text-[#E9A76A]" />
          <span>BIBR1532 Pocket</span>
        </div>
      </div>

      {/* Right: Quick Action Controls */}
      <div className="flex items-center gap-2">
        {onFocusInhibitor && (
          <button
            onClick={onFocusInhibitor}
            title="Center 3D camera on BIBR1532 allosteric pocket"
            className="px-2.5 py-1 text-xs rounded-lg bg-[#18232D] hover:bg-[#202F3C] border border-[#202F3C] hover:border-[#E9A76A]/40 text-[#E9A76A] transition flex items-center gap-1.5 cursor-pointer font-medium"
          >
            <Crosshair className="w-3 h-3" />
            <span>Focus Inhibitor</span>
          </button>
        )}
      </div>
    </div>
  );
};
