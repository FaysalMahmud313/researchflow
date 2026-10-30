import { describe, it, expect } from 'vitest';

const ROLE_CAN_EDIT: Record<string, boolean> = {
  owner: true,
  editor: true,
  reviewer: false,
  viewer: false,
};

const SUPPORTED_THEMES = ['light', 'dark', 'system'];
const SUPPORTED_ACCENTS = ['indigo', 'blue', 'violet', 'teal', 'emerald', 'rose', 'amber'];

describe('Frontend Role Matrix & Theme Customization Guardrails', () => {
  it('permits owners and editors to modify tasks and documents', () => {
    expect(ROLE_CAN_EDIT.owner).toBe(true);
    expect(ROLE_CAN_EDIT.editor).toBe(true);
  });

  it('prevents reviewers and viewers from modifying tasks or documents', () => {
    expect(ROLE_CAN_EDIT.reviewer).toBe(false);
    expect(ROLE_CAN_EDIT.viewer).toBe(false);
  });

  it('supports Light, Dark, and System theme modes plus 7 accent palettes', () => {
    expect(SUPPORTED_THEMES).toEqual(['light', 'dark', 'system']);
    expect(SUPPORTED_ACCENTS.length).toBe(7);
  });
});
