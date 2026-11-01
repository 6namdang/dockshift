/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

interface DockShiftIconProps {
  className?: string;
  size?: number;
  variant?: 'dark' | 'transparent';
  dotColor?: string;
}

/**
 * Official DockShift Brand Icon.
 * Features the two interlocking amber and seafoam-teal elliptical rings
 * with the central focus point, matching the design specification.
 */
export const DockShiftIcon: React.FC<DockShiftIconProps> = ({
  className = '',
  size = 36,
  variant = 'transparent',
  dotColor = '#FFFFFF'
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`select-none flex-shrink-0 ${className}`}
      aria-label="DockShift icon"
    >
      {variant === 'dark' && (
        <rect width="100" height="100" rx="24" fill="#0E1718" />
      )}

      {/* Lens Overlap Fill */}
      <ellipse
        cx="50"
        cy="50"
        rx="10.5"
        ry="25"
        fill="#3B8E7D"
        fillOpacity="0.28"
      />

      {/* Left Elliptical Ring (Warm Golden Amber) */}
      <ellipse
        cx="43.5"
        cy="50"
        rx="16"
        ry="27.5"
        stroke="#E6A845"
        strokeWidth="4.5"
        strokeLinecap="round"
      />

      {/* Right Elliptical Ring (Crisp Mint Teal) */}
      <ellipse
        cx="56.5"
        cy="50"
        rx="16"
        ry="27.5"
        stroke="#4EBEA4"
        strokeWidth="4.5"
        strokeLinecap="round"
      />

      {/* Central Core Focus Dot */}
      <circle cx="50" cy="50" r="4.2" fill={dotColor} />
    </svg>
  );
};

interface DockShiftLogoProps {
  className?: string;
  iconSize?: number;
  textColor?: string;
  subtitle?: string;
}

/**
 * DockShift Brand Lockup (Icon + Wordmark)
 * Clean, minimal, professional alignment matching the brand design specification.
 */
export const DockShiftLogo: React.FC<DockShiftLogoProps> = ({
  className = '',
  iconSize = 30,
  textColor = '#E9F0F3',
  subtitle
}) => {
  return (
    <div className={`flex items-center gap-2.5 select-none ${className}`}>
      <DockShiftIcon size={iconSize} variant="transparent" dotColor="#59C9C0" />
      <div className="flex flex-col justify-center">
        <div
          className="flex items-center font-bold tracking-tight text-lg leading-none"
          style={{ color: textColor }}
        >
          <span>Dock</span>
          <span className="text-[#59C9C0]">Shift</span>
        </div>
        {subtitle && (
          <span className="text-[10px] font-mono tracking-wider uppercase text-[#90A4AF] mt-0.5">
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
};
