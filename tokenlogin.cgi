#!/usr/bin/perl

use strict;
use warnings;

use CGI;
use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $cont = "/";
my $authd = 0;
my $login = 0;
my $expired = 0;
my $xss_attempt;
my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
my $id;
my $uid;

if ( exists $ENV{"HTTP_SESSION"} ) {
        my @session_data = split/\&/,$ENV{"HTTP_SESSION"};
        my @tuple;
        for my $unprocd_tuple (@session_data) {
                @tuple = split/\=/,$unprocd_tuple;
                if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
                        $session{$tuple[0]} = $tuple[1];
                }
        }
}

if (exists $session{"id"} and $session{"id"} =~ /^([0-9A-Z]+)$/) {
	$id = $1;
	$authd++;
} 


if (exists $ENV{"QUERY_STRING"} and $ENV{"QUERY_STRING"} =~ /^.*&?cont=(.+)&?$/i) {
        $cont = $1; 
}

if (not $authd) {

	#process auth data

	if (exists $ENV{"REQUEST_METHOD"} and $ENV{"REQUEST_METHOD"} eq "POST") {	
		$login++;
		my $str;
		if (exists $session{"tries"}) {
			$session{"tries"} = $session{"tries"}+1;
		}
		else {
			$session{"tries"} = 1;	
		}
        	while (<STDIN>) {	
                	$str .= $_;
        	}
		my $spc = " "; 
		$str =~ s/\+/$spc/ge;
		my %auth_params;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
		if ( exists $auth_params{"auth_token1"} and exists $auth_params{"token"}  ) {

			my $token = uc($auth_params{"token"});
			my $auth_token = $auth_params{"auth_token1"};
			my $uid;
			if ($auth_token eq $session{"auth_token1"}) {
	   	     my $con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
				if ($con) {
					my $prep_stmt = $con->prepare("SELECT value,expiry,issued_to,privileges FROM tokens WHERE value=? LIMIT 1");
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($token);
						if ($rc) {
							my @valid = $prep_stmt->fetchrow_array();	
							if (@valid) {	
								if ($token eq $valid[0]) {
									#print "X-Debug-0: valid token\r\n";
									my $time = time;
									if ($time < $valid[1]) {
										#print "X-Debug-1: unexpired token\r\n";	
										$authd++;
										$session{"id"} = $valid[0];
										$id = $valid[0];
										$session{"token_expiry"} = $valid[1];
										$session{"name"} = $valid[2];
										$session{"privileges"} = $valid[3];
										$uid = $valid[0];
									}
									else {
										$expired++;
									}
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt->errstr, $/;  
					}	
								
				}
				else {
					print STDERR $!;
				}
				$con->disconnect();	
			}
			else {
				$xss_attempt++;
			}
		}
	}
}

print "Content-Type: text/html\r\n";
my $res = "";

#auth failed due to incorrect 
#pass or incorrect auth token

if (not $authd) {

	my $auth_token = gen_token();
	$session{"auth_token1"} = $auth_token;
	my @new_sess_array;
	for my $sess_key (keys %session) {
		push @new_sess_array, $sess_key."=".$session{$sess_key};	
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
		
	$res .=
		'<!DOCTYPE html>
		<html lang="en">
		<head>';
		if ($login) {
			$res .=
			'<title>Spanj: Exam Management Information System - Login Failed</title>';
		}
		else {
			$res .=
			'<title>Spanj: Exam Management Information System - User Login</title>';
		}
	$res .=	
		'<BASE target="_parent">
		</head>
		<body>	
		<br/>
		<p><a href="/">Home</a> --&gt; <a href="/login.html">Login Options</a> --&gt; <a href="/cgi-bin/tokenlogin.cgi?cont=' . 
		$cont . 
		'"> Login with Access Token</a><p><h5>Spanj Exam Management Information System</h5>';
	if ($login) {
		$res .= '<p>Return <a href="/">Home</a> or go to the general <a href="/login.html">Login Page</a>';
		if ($expired) {
			$res .=	'<p><span style="color: red"><i>That access token is expired. Get a new one from the Administrator.</i></span><br>';
		}
		else {
			$res .=	'<p><span style="color: red"><i>Unknow access token</i></span><br>';
		}
	}
	
	if ($xss_attempt) {
		$res .= '<span style="color: red"><i>PS: I saw what you did to my tokens</i></span></br>'; 
	}
	$res .=
		'<form autocomplete="off" method="POST" action="/cgi-bin/tokenlogin.cgi?cont='.$cont.'">'.
		'<table>
		<tr>
		<td>
		<label for="token">Access Token</label>
		</td>
		<td>
		<input type="text" name="token" size="35"/>';

		$res .=	"<input type=\"hidden\" name=\"auth_token1\" value=\"$auth_token\"/>";

		$res .=	'</td>
			</tr>

			<tr>
			<td>
			<input type="submit" name="submit" value="Login"/>
			</td>
			<td></td>
			</tr>

			</table>
			</form>

			</body>

			</html>';
	my $content_len = length($res);
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
}
	#auth successful
elsif ($authd) {
	#correct pass/user-name provided
	if ($login) {	
		#$session{"auth_token1"} = "";
		my @new_sess_array;
		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};	
		}
		my $new_sess = join ('&',@new_sess_array);
		print "X-Update-Session: $new_sess\r\n";

		my @today = localtime; 
		my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	        open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
       		if ($log_f) {
               		@today = localtime;	
			my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
			flock ($log_f, LOCK_EX);
			seek($log_f, 0, SEEK_END);
               		print $log_f "$id LOGIN $time\n";
			flock($log_f, LOCK_UN);	
               		close $log_f;
       		}
	}
	
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: $cont\r\n";

	my $clean_url = htmlspecialchars($cont);	
        my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		<base target=\"_parent\">
		</head>
           	<body>
                You should have been redirected to <a href=\"$clean_url\">$clean_url</a>. If you were not, <a href=\"$clean_url\">Click Here</a> 
		</body>
                </html>";
	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
}


sub gen_token {
	my $len = 5 + int(rand 6);
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}


 
