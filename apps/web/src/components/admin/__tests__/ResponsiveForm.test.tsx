import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FormField } from '../ResponsiveForm';

describe('admin field labels', () => {
  it('associates a visible label with its input, including a select wrapper', () => {
    render(<FormField label="Project type" htmlFor="project-type"><div><select id="project-type"><option>Novel</option></select></div></FormField>);
    expect(screen.getByLabelText('Project type')).toBe(screen.getByRole('combobox'));
  });
});
