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
Version:        1.0
Release:        0
Summary:        Client-side hooks for git and git-based osc
License:        GPL-2.0-or-later
Group:          Development/Tools/Other
URL:            https://github.com/openSUSE/git-obs-hooks
Source:         git-obs-hooks-%{version}.tar.gz
Requires:       git-obs-hooks-common >= %{version}
BuildArch:      noarch

%description
Client-side hooks for git and git-based osc operations.

%package common
Summary:        Git hooks for the OBS and Gitea ecosystem
Group:          Development/Tools/Other
Requires:       git-core
Requires:       git-lfs
Requires:       osc
BuildArch:      noarch

%description common
Manage and run git hooks in the Open Build Service (OBS) ecosystem,
for both client-side (git, osc) and server-side (Gitea) operations.

%package gitea
Summary:        Server-side git hooks for Gitea
Group:          Development/Tools/Other
Requires:       git-obs-hooks-common >= %{version}
BuildArch:      noarch

%description gitea
Server-side git hooks for Gitea based on Gitea's generated hooks.

%prep
%autosetup

%build

%install
install -d %{buildroot}/usr/libexec/git-obs-hooks
install -m 644 src/git-diff-order %{buildroot}/usr/libexec/git-obs-hooks/
install -m 755 src/git-obs-hooks-install %{buildroot}/usr/libexec/git-obs-hooks/
install -m 755 src/git-obs-hooks-uninstall %{buildroot}/usr/libexec/git-obs-hooks/
install -m 755 src/gitea-hooks-install %{buildroot}/usr/libexec/git-obs-hooks/
install -m 755 src/gitea-hooks-uninstall %{buildroot}/usr/libexec/git-obs-hooks/
cp -rv src/{all-hooks,gitea,git-obs,common} %{buildroot}/usr/libexec/git-obs-hooks/

%files
%dir /usr/libexec/git-obs-hooks/git-obs
/usr/libexec/git-obs-hooks/git-obs/*
/usr/libexec/git-obs-hooks/git-obs-hooks-install
/usr/libexec/git-obs-hooks/git-obs-hooks-uninstall

%files gitea
%dir /usr/libexec/git-obs-hooks/gitea
/usr/libexec/git-obs-hooks/gitea/*
/usr/libexec/git-obs-hooks/gitea-hooks-install
/usr/libexec/git-obs-hooks/gitea-hooks-uninstall

%post gitea
if getent passwd gitea >/dev/null; then
  GITEA_HOME=$(getent passwd gitea | cut -d: -f6)
  if [ -n "${GITEA_HOME}" ] && [ -d "${GITEA_HOME}" ]; then
    runuser -u gitea -- /usr/libexec/git-obs-hooks/gitea-hooks-install || :
  fi
fi

%postun gitea
if [ "$1" -eq 0 ] && getent passwd gitea >/dev/null; then
  GITEA_HOME=$(getent passwd gitea | cut -d: -f6)
  if [ -n "${GITEA_HOME}" ] && [ -d "${GITEA_HOME}" ]; then
    runuser -u gitea -- /usr/libexec/git-obs-hooks/gitea-hooks-uninstall || :
  fi
fi

%files common
%doc README.md
%license LICENSE
%dir /usr/libexec
%dir /usr/libexec/git-obs-hooks/
/usr/libexec/git-obs-hooks/common
/usr/libexec/git-obs-hooks/git-diff-order
%dir /usr/libexec/git-obs-hooks/all-hooks/
/usr/libexec/git-obs-hooks/all-hooks/*

%changelog
