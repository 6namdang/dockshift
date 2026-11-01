/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import {
  Lightbulb,
  Crosshair,
  Sliders,
  GitCompare,
  Search,
  BookOpen,
  Keyboard,
  ExternalLink
} from 'lucide-react';
import { DockShiftLogo } from './DockShiftLogo';

export type NavigationTab =
  | 'discover'
  | 'screen'
  | 'playground'
  | 'compare'
  | 'literature';

interface NavigationSidebarProps {
  activeTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  noteCount: number;
  onOpenNotes?: () => void;
}

export const NavigationSidebar: React.FC<NavigationSidebarProps> = ({
  activeTab,
  onSelectTab,
  noteCount,
  onOpenNotes
}) => {
  const navItems: {
    id: NavigationTab;
    num: number;
    label: string;
    icon: React.FC<{ className?: string }>;
    desc: string;
  }[] = [
    {
      id: 'discover',
      num: 1,
      label: 'Discover',
      icon: Lightbulb,
      desc: 'Biology guide & challenges'
    },
    {
      id: 'screen',
      num: 2,
      label: 'Screen',
      icon: Crosshair,
      desc: 'QSAR candidate screening'
    },
    {
      id: 'playground',
      num: 3,
      label: 'Molecular Playground',
      icon: Sliders,
      desc: '3D Structure & component inspection'
    },
    {
      id: 'compare',
      num: 4,
      label: 'Compare',
      icon: GitCompare,
      desc: 'Candidate benchmark matrix'
    },
    {
      id: 'literature',
      num: 5,
      label: 'Literature',
      icon: Search,
      desc: 'Scientific literature query'
    }
  ];

  return (
    <aside
      aria-label="Primary Navigation"
      className="w-64 flex-shrink-0 h-full bg-[#0B1118] border-r border-[#202F3C] flex flex-col justify-between text-[#E9F0F3] select-none z-30"
    >
      {/* Top Section: Brand Header & Now Exploring Target Info */}
      <div className="flex flex-col">
        {/* Clean, Minimal Brand Lockup: Only 'DockShift', no subtitle or tagline */}
        <div className="px-4 py-3.5 border-b border-[#202F3C] flex items-center justify-between">
          <button
            onClick={() => onSelectTab('playground')}
            title="DockShift — Molecular Docking & Telomerase Investigation"
            className="flex items-center text-left cursor-pointer hover:opacity-95 transition"
          >
            <DockShiftLogo iconSize={28} textColor="#E9F0F3" />
          </button>
        </div>

        {/* Now Exploring Section: Preserved Scientific Target Metadata */}
        <div className="p-3 border-b border-[#202F3C]">
          <div className="p-3 rounded-xl bg-[#18232D] border border-[#202F3C] shadow-sm">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] font-mono tracking-wider uppercase text-[#59C9C0] font-semibold flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[#59C9C0] animate-pulse" />
                Now Exploring
              </span>
              <a
                href="https://www.rcsb.org/structure/9Q14"
                target="_blank"
                rel="noreferrer"
                title="View 9Q14 in RCSB Protein Data Bank"
                className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-[#59C9C0]/15 text-[#59C9C0] border border-[#59C9C0]/30 hover:border-[#59C9C0] transition flex items-center gap-1"
              >
                <span>PDB: 9Q14</span>
                <ExternalLink className="w-2.5 h-2.5" />
              </a>
            </div>

            <div className="font-semibold text-xs text-[#E9F0F3] leading-snug">
              Human Telomerase
            </div>
            <div className="text-[11px] text-[#90A4AF] mt-0.5">
              Catalytic Core Complex (Cryo-EM 3.0 Å)
            </div>

            <div className="mt-2.5 pt-2 border-t border-[#202F3C]/80 flex items-center justify-between text-[11px]">
              <span className="text-[#90A4AF]">Target Site</span>
              <span className="font-mono text-[#E9A76A] font-medium text-[10px] bg-[#E9A76A]/10 px-1.5 py-0.5 rounded border border-[#E9A76A]/20">
                BIBR1532 Pocket
              </span>
            </div>
          </div>
        </div>

        {/* Navigation Section */}
        <nav className="p-2 space-y-1">
          <div className="text-[10px] font-mono uppercase tracking-wider text-[#627783] px-2 py-1 font-semibold">
            Workflow Stages
          </div>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                title={`[${item.num}] ${item.label} — ${item.desc}`}
                className={`w-full px-2.5 py-2 rounded-xl flex items-center gap-2.5 transition text-left cursor-pointer group relative ${
                  isActive
                    ? 'bg-[#18232D] text-[#59C9C0] border border-[#59C9C0]/30 shadow-sm'
                    : 'text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#18232D]/60'
                }`}
              >
                {/* Active Indicator Bar */}
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-1 bg-[#59C9C0] rounded-r-full" />
                )}

                <div className="relative flex-shrink-0">
                  <Icon className="w-4 h-4" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-xs truncate ${
                        isActive ? 'font-semibold text-[#E9F0F3]' : 'font-medium'
                      }`}
                    >
                      {item.label}
                    </span>
                    <span
                      className={`text-[9px] font-mono font-bold px-1 rounded ${
                        isActive
                          ? 'bg-[#59C9C0] text-[#0B1118]'
                          : 'bg-[#18232D] text-[#627783] border border-[#202F3C]'
                      }`}
                    >
                      {item.num}
                    </span>
                  </div>
                  <div className="text-[10px] text-[#627783] truncate mt-0.5">
                    {item.desc}
                  </div>
                </div>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: Research Notes & Global Shortcut Helpers */}
      <div className="p-3 border-t border-[#202F3C] space-y-2">
        {onOpenNotes && (
          <button
            onClick={onOpenNotes}
            title="Open Lab Research Notes (Ctrl+Shift+N)"
            className="w-full px-3 py-2 rounded-xl bg-[#18232D]/70 hover:bg-[#18232D] border border-[#202F3C] hover:border-[#59C9C0]/30 text-[#90A4AF] hover:text-[#E9F0F3] transition flex items-center justify-between cursor-pointer group"
          >
            <div className="flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-[#59C9C0] group-hover:scale-110 transition-transform" />
              <span className="text-xs font-medium">Research Notes</span>
            </div>
            <div className="flex items-center gap-1.5">
              {noteCount > 0 && (
                <span className="px-1.5 py-0.5 text-[9px] font-mono font-bold rounded-full bg-[#E9A76A] text-[#0B1118]">
                  {noteCount}
                </span>
              )}
              <kbd className="text-[9px] font-mono px-1 py-0.5 rounded bg-[#0B1118] text-[#627783] border border-[#202F3C]">
                ^⇧N
              </kbd>
            </div>
          </button>
        )}

        <div className="px-2 py-1.5 rounded-lg bg-[#18232D]/40 border border-[#202F3C]/50 flex items-center justify-between text-[10px] text-[#627783]">
          <span className="flex items-center gap-1">
            <Keyboard className="w-3 h-3 text-[#59C9C0]" />
            <span>Shortcuts:</span>
          </span>
          <span className="font-mono">Press 1-5 to switch</span>
        </div>
      </div>
    </aside>
  );
};
