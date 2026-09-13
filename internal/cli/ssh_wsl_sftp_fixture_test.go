package cli

import (
	"context"
	"errors"
	"net"
	"os"
	"os/exec"
	"strings"
	"testing"
	"testing/synctest"
)

func TestLoopbackSFTPClientSurvivesTestContextCancellation(t *testing.T) {
	root := t.TempDir()
	synctest.Test(t, func(t *testing.T) {
		client := newLoopbackSFTPClient(t, root)
		t.Cleanup(func() {
			if !errors.Is(t.Context().Err(), context.Canceled) {
				t.Fatal("test context was not canceled before cleanup")
			}
			// Let cancellation watchers finish before the fixture's own cleanup.
			synctest.Wait()
			if _, err := client.Stat(wslStageRoot); err != nil {
				t.Fatalf("SFTP fixture closed before orderly client cleanup: %v", err)
			}
		})
	})
}

func TestLoopbackSFTPClientReportsServerFailure(t *testing.T) {
	const child = "CRABBOX_TEST_LOOPBACK_SFTP_SERVER_FAILURE"
	if os.Getenv(child) == "1" {
		root := t.TempDir()
		synctest.Test(t, func(t *testing.T) {
			var serverConn net.Conn
			newLoopbackSFTPClientWithServerConn(t, root, func(conn net.Conn) net.Conn {
				serverConn = conn
				return conn
			})
			// Close the server while its packet read is blocked, before client
			// cleanup, to require the fixture to report the unexpected error.
			synctest.Wait()
			if err := serverConn.Close(); err != nil {
				t.Fatal(err)
			}
			synctest.Wait()
		})
		return
	}

	command := exec.CommandContext(t.Context(), os.Args[0], "-test.run=^TestLoopbackSFTPClientReportsServerFailure$", "-test.v")
	command.Env = append(os.Environ(), child+"=1")
	output, err := command.CombinedOutput()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != 1 {
		t.Fatalf("server failure must fail the fixture: %v\n%s", err, output)
	}
	const want = "SFTP server: error reading packet length: 0 of 4: io: read/write on closed pipe"
	if !strings.Contains(string(output), want) {
		t.Fatalf("missing exact server failure %q:\n%s", want, output)
	}
}
