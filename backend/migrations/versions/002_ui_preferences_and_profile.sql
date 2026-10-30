-- Migration 002: Add theme, accent, density, reduced_motion, and professional_title to user_profiles
ALTER TABLE user_profiles ADD COLUMN professional_title TEXT NOT NULL DEFAULT '';
ALTER TABLE user_profiles ADD COLUMN avatar_color TEXT NOT NULL DEFAULT 'indigo';
ALTER TABLE user_profiles ADD COLUMN theme_mode TEXT NOT NULL DEFAULT 'light';
ALTER TABLE user_profiles ADD COLUMN accent_color TEXT NOT NULL DEFAULT 'indigo';
ALTER TABLE user_profiles ADD COLUMN ui_density TEXT NOT NULL DEFAULT 'compact';
ALTER TABLE user_profiles ADD COLUMN reduced_motion INTEGER NOT NULL DEFAULT 0;
