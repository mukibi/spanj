#!/usr/bin/perl
use strict;
use warnings;

use CGI;
require "./conf.pl";

our($db,$db_user,$db_pwd);
my $logged_in = 0;
my $uname;

my $qstr = "?cont=/";

if (exists $ENV{"QUERY_STRING"} and length($ENV{"QUERY_STRING"}) > 0) {
	$qstr = "?" . $ENV{"QUERY_STRING"};
}

#session defined--good sign
if (exists $ENV{"HTTP_SESSION"}) {
	my %session;
	my @sess_data = split/&/,$ENV{"HTTP_SESSION"};
	for my $sess_kv_pair (@sess_data) {
		my @sess_tuple = split/=/,$sess_kv_pair;
		$session{$sess_tuple[0]} = $sess_tuple[1];
	}
	if (exists $session{"id"} and $session{"id"} =~ /^[0-9A-Z]+$/) {

		if (exists $session{"name"}) {
			$uname = $session{"name"};
			my $space = " ";
			$uname =~ s/\+/$space/ge;
			$uname =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$logged_in++;
			if (exists $session{"token_expiry"} and $session{"token_expiry"} ne "0")  {
				if ($session{"token_expiry"} < time) {
					$session{"id"} = "";
					$logged_in = 0;
				} 
			}
		}
	}
}

my $body;

if ($logged_in) {
	$body =
'
<!DOCTYPE html>
<html>
<head>
<title>Spanj::Exam Management Information System::Check Login</title>
<base target="_parent">
</head>
<body>
<a href="/cgi-bin/logout.cgi' . $qstr . '"><h5>Logout(' .$uname.
')</h5></a>
</body>
</html>
'

}
else {
	$body = 
'<!DOCTYPE html>
<html>
<head>
<title>Spanj::Exam Management Information System::Check Login</title>
<base target="_parent">
</head>
<body>
<a href="/login.html' . $qstr .'"><h5>Login</h5></a>
</body>
</html>'
}

my $content_len = length($body);

print 
	"Content-Type: text/html; charset=UTF-8\r\n" .
	"Content-Length: $content_len\r\n" .
	"\r\n" .
	$body;

