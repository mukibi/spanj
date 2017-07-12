#!/usr/bin/perl

use strict;
use warnings;

my $content = "<HTML><HEAD><TITLE>Test demons</TITLE></HEAD><BODY><EM>Hello</EM></BODY></HTML>";

my $child_pid = fork();

#child
if (not $child_pid) {
=pod
	use POSIX;

	close STDIN;
	close STDOUT;
	close STDERR;

	POSIX::setsid();
=cut
	sleep(10);

	exit(0);
}
else {
	$SIG{CHLD} = 'IGNORE';
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

print "\r\n";
print $content;

