#
# spec file for package git-obs-hooks
#
# Copyright (c) 2026 SUSE LLC
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#


Name:           git-obs-hooks
Version:        20260309T114850.955d304
Release:        0
Summary:        Git hooks for the OBS and Gitea ecosystem
License:        GPL-2.0-or-later
Group:          Development/Tools/Other
URL:            https://github.com/openSUSE/git-obs-hooks
Source0:        %{name}-%{version}.tar.gz
Source1:        rpmlintrc
Requires:       git-core
Requires:       git-lfs
BuildArch:      noarch

%description
Manage and run git hooks in the Open Build Service (OBS) ecosystem,
for both client-side (git, osc) and server-side (Gitea) operations.

%package gitea
Summary:        Server-side git hooks for Gitea
Group:          Development/Tools/Other
Requires:       %{name} >= %{version}
BuildArch:      noarch

%description gitea
This subpackage configures server-side hooks for Gitea.
It contains a copy of Gitea's generated hooks.

%package git-obs
Summary:        Client-side git hooks for git and osc
Group:          Development/Tools/Other
Requires:       %{name} >= %{version}
BuildArch:      noarch

%description git-obs
This subpackage configures client-side hooks for git and git-based osc.

%prep
%autosetup

%build

%install
mkdir -p %{buildroot}%{_libexecdir}/%{name}/
cp -rv src/{all-hooks,gitea,git-obs,common} %{buildroot}%{_libexecdir}/%{name}/

%post gitea
GITEA_HOME=%{_localstatedir}/lib/gitea/data/home
GITEA_HOOKS_PATH=%{_libexecdir}/git-obs-hooks/gitea
if [ ! -d "$GITEA_HOME" ]; then
  echo "WARNING: gitea user home does not exist, skipping hook setup"
  exit 0
fi
CURRENT_HOOKS_PATH=$(git config --file "$GITEA_HOME/.gitconfig" --get core.hooksPath ||:)
if [ -n "$CURRENT_HOOKS_PATH" ] && [ "$CURRENT_HOOKS_PATH" != "$GITEA_HOOKS_PATH" ]; then
  echo "WARNING: gitea's git configuration currently uses a different core.hooksPath:"
  echo "  current : '$CURRENT_HOOKS_PATH'"
  echo "  expected: '$GITEA_HOOKS_PATH'"
  echo "The current value will be overwritten by the package."
fi
if [ "$CURRENT_HOOKS_PATH" != "$GITEA_HOOKS_PATH" ]; then
  echo "INFO: Setting gitea user's core.hooksPath to '$GITEA_HOOKS_PATH':"
  echo "  git config --file $GITEA_HOME/.gitconfig core.hooksPath $GITEA_HOOKS_PATH"
  git config --file "$GITEA_HOME/.gitconfig" core.hooksPath "$GITEA_HOOKS_PATH"
fi

%files
%doc README.md
%license LICENSE
%dir %{_libexecdir}/git-obs-hooks/
%{_libexecdir}/git-obs-hooks/common
%dir %{_libexecdir}/git-obs-hooks/all-hooks/
%{_libexecdir}/git-obs-hooks/all-hooks/*

%files gitea
%dir %{_libexecdir}/git-obs-hooks/gitea
%{_libexecdir}/git-obs-hooks/gitea/*

%files git-obs
%dir %{_libexecdir}/git-obs-hooks/git-obs
%{_libexecdir}/git-obs-hooks/git-obs/*

%changelog
