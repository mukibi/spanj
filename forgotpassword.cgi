#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Digest::SHA qw /sha1_hex/;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $id;
my $authd = 0;


my $u_name = undef;
my $u_id = undef;
my $stage = 1;
my $token = "";
my $url_rec_code = undef;

if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?stage=(\d+)\&?/ ) {	
		$stage = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?u_name=([A-Za-z0-9_\-\.]{1,16})\&?/ ) {	
		$u_name = $1;
		$stage = 2;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?u_id=([0-9]+)\&?/ ) {	
		$u_id = $1;	
		$stage = 2;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?token=(.+)\&?/ ) {	
		$token = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?rec_code=(.+)\&?/ ) {	
		$url_rec_code = $1;
	}
}

if ( exists $ENV{"HTTP_SESSION"} ) {
	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	if (exists $session{"id"} and $session{"id"} =~ /^([0-9]+)$/) {
		$id = $1;
		$authd++;	
	}
}

if ($authd) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /cgi-bin/logout.cgi?cont=/cgi-bin/forgotpassword.cgi?stage=$stage\r\n";
	print "Content-Type: text/html; charset=ISO-8859-1\r\n";
       	my $res = 
               	qq{
		<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href="/cgi-bin/logout.cgi?cont=/cgi-bin/forgotpassword.cgi?stage=$stage">/cgi-bin/logout.cgi?cont=/cgi-bin/forgotpassword.cgi?stage=$stage</a>. If you were not, <a href="/cgi-bin/logout.cgi?cont=/cgi-bin/forgotpassword.cgi?stage=$stage">Click Here</a> 
		</body>
                </html>};

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
	exit 0;
}

my %auth_params;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	
	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
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
}

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/forgotpassword.cgi?stage=$stage">Forgot Password</a>
	<hr> 
};

my $conf_code = gen_token();
my $content = '';
my $con;
my %matched;
my $feedback = '';

#system checks the username in the
#system handles multiple matches
#for a given username 
STAGE2: {
   if ($stage == 2) {
	if (exists $auth_params{"u_name"}) {	
		my $possib_u_name = $auth_params{"u_name"};
		if ($possib_u_name =~ /^[A-Za-z0-9_\-\.]{1,16}$/) {
			$u_name = $possib_u_name;
		}
		else {
			$feedback = "Invalid username. A valid username consists of the alphanumeric characters(A-Z, 0-9) and any of the following punctuation marks: _,- or .";
		}
	}

	unless (defined $u_name or defined $u_id) {
		$stage = 1;
		last STAGE2;
	}
	if (exists $auth_params{"recover"}) {
		if (exists $auth_params{"confirm_code"}) {
			if ($session{"confirm_code"} ne $auth_params{"confirm_code"}) {
				$feedback = "Unknow authentication token. Do not alter the hidden values in the HTTP form.";
				$stage = 1;
				last STAGE2;
			}
		}
		else {
			$feedback = "No authentication token sent. Refresh your authentication tokens by reloading this page";
			$stage = 1;
			last STAGE2;
		}
	}
	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
	if ($con) {
		my $qry = "SELECT u_id, sec_qstn1, sec_qstn2 FROM users WHERE u_name=?";
		if (defined $u_id) {
			$qry = "SELECT u_id, sec_qstn1, sec_qstn2 FROM users WHERE u_id=?";
		}	
		my $prep_stmt = $con->prepare($qry);
		if ($prep_stmt) {
			my $rc;
			if (defined $u_id) {
				$rc = $prep_stmt->execute($u_id);
			}
			else {
				$rc = $prep_stmt->execute(lc($u_name));
			}
			if ($rc) {
				while (my @rslts = $prep_stmt->fetchrow_array()) {	
					$matched{$rslts[0]} = [$rslts[1], $rslts[2]];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM users: ", $prep_stmt->errstr,$/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM users: ", $prep_stmt->errstr, $/;  
		}
		$con->disconnect();
	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
	my $num_matches = keys %matched;
	#no such user
	if ($num_matches == 0) {
		$feedback = "No such user.";
		sleep 1;
		$stage = 1;
		last STAGE2; 
	}
	
	#only 1 user goes by this username
	#gist of this stage
	if ($num_matches == 1) {
		$u_id = (keys %matched)[0];
		$session{"recover_uid"} = $u_id;
		my ($qstn1, $qstn2) = @{$matched{$u_id}};	
		$content = 
		
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
</head>

<body>
$header
To reset your password, answer the following security questions:<br><br>
<form autocomplete="off" action="/cgi-bin/forgotpassword.cgi?stage=4" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<table>
<tr><td><LABEL for="ans1" style="font-weight: bold">Security Question 1:&nbsp;&nbsp;</LABEL><LABEL for="ans1">$qstn1</LABEL>
<tr><td><LABEL for="ans1" style="font-weight: bold">Answer:</LABEL><INPUT type="text" name="ans1" value="">
<tr><td colspan="2">
<tr><td><LABEL for="ans2" style="font-weight: bold">Security Question 2:&nbsp;&nbsp;</LABEL><LABEL for="ans1">$qstn2</LABEL>
<tr><td><LABEL for="ans2" style="font-weight: bold">Answer:</LABEL><INPUT type="text" name="ans2" value="">
<tr><td><INPUT type="submit" name="send" value="Send">
</table>
</form>
</body>
</html>
};
	}
	#more than 1 user goes by this
	#username. Enter a disambugation phase
	elsif ($num_matches > 1) { 
		$stage = 3;
		last STAGE2;		
	} 
  }
}

#process reset password
STAGE5: {	
	$feedback = '';
	if ($stage == 5) {
		my $success = 0;
		unless (exists $session{"recover_uid"} and $session{"recover_uid"} =~ /^\d+$/) {
			$stage = 1;
			last STAGE5;	
		}
		unless (exists $session{"recover_code"} and defined $url_rec_code) {
			$stage = 1;
			last STAGE5;
		}

		unless ($session{"recover_code"} eq $url_rec_code) {
			$stage = 1; 
			last STAGE5;
		}
		$u_id = $session{"recover_uid"};
		my $new_pass1 = $auth_params{"password1"};
		my $new_pass2 = $auth_params{"password2"};

		if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"}) { 
	   	  if ($session{"confirm_code"} eq $auth_params{"confirm_code"}) {
		if ($new_pass1 eq $new_pass2) {
			if (length($new_pass1) >= 6) { 
				my $nu_salt = gen_token(1);
				my $nu_pass_hash = uc( sha1_hex($new_pass1 . $nu_salt) );
     				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
				if ($con) {
					my $prep_stmt = $con->prepare("UPDATE users SET password=?, salt=? WHERE u_id=? LIMIT 1");
			
					if ($prep_stmt) {
						my $rc = $prep_stmt->execute($nu_pass_hash, $nu_salt, $u_id);
						if ($rc) {
							$success = 1;
							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        						if ($log_f) {
                						@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log reset password for $u_id due to flock error: $!$/"; 
								seek ($log_f, 0, SEEK_END);
		 						print $log_f "$u_id RESET PASSWORD $time\n";
								flock ($log_f, LOCK_UN);	
                						close $log_f;
        						}
							else {
								print STDERR "Could not log change password for $id: $!\n";
							}	
						}
						else {
							print STDERR "Could not execute UPDATE users: ", $prep_stmt->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare UPDATE users: ", $prep_stmt->errstr, $/;  
					}
					$con->commit();
					$con->disconnect();
				}
			}
			else {
				$feedback = 'A valid password should be atleast 6 characters long.';
			}
		}
		else {
			$feedback = 'The 2 passwords entered do not match.'
		}
	}
	#bogus auth token sent?
	else {
		$feedback = "No authentication tokens received. Refresh your tokens by reloading this page.";
	}
    }
	#no auth token sent?
    else {
 	$feedback = "Invalid authentication tokens received. Do not alter any of the hidden values in the HTTP form.";
    }

	if ($success) {
		$session{"recover_uid"} = "";
		$session{"recover_code"} = "";
		$content = 
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
</head>
<body>
$header
<em>Your password has been successfully reset! To login using your new password, got to <a href="/cgi-bin/pwlogin.cgi">/cgi-bin/pwlogin.cgi</a>.
</body>
</html>
};
	}
	else {
		my $rec_code = gen_token(1);
		$session{"recover_code"} = $rec_code;
		$content =
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
<script>
function check_match() {
	var pass1 = document.getElementById("password1").value;
	var pass2 = document.getElementById("password2").value;
	if (pass1 !== pass2) {
		document.getElementById("match_feedback").innerHTML = '<tr><td colspan="2">The 2 passwords entered do not match';
		return false;
	}
	else {
		document.getElementById("reset_form").submit();
	}
}
</script>
</head>

<body>
$header
<span style="color: red">$feedback</span>
<p>Enter your new password
<FORM action="/cgi-bin/forgotpassword.cgi?stage=5&rec_code=$rec_code" method="POST" id="reset_form">
<INPUT type="hidden" value="$conf_code" name="confirm_code">
<span style="color: red" id="match_feedback"></span>
<TABLE>
<tr>
<td><LABEL for="password1">New Password</LABEL>
<td><INPUT type="password" name="password1" value="" id="password1">
<tr>
<td><LABEL for="password2">Confirm New Password</LABEL>
<td><INPUT type="password" name="password2" value="" id="password2">
<tr>
<td><INPUT type="submit" name="reset" value="Reset" onclick="check_match()">
</TABLE>
</FORM>
};
	}
  }
}
#process answers to security questions
#on success, write out password reset page
STAGE4: {
	if ($stage == 4) {
		my $success = 0;
		my $sess_rec_code = undef;
		my ($qstn1, $qstn2) = ("", "");
		unless (exists $session{"recover_uid"} and $session{"recover_uid"} =~ /^\d+$/) {	
			$stage = 1;
			last STAGE4;
		}
		$u_id = $session{"recover_uid"};	

	if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"}) {
	   if ($session{"confirm_code"} eq $auth_params{"confirm_code"}) { 
		if (exists $auth_params{"ans1"} and exists $auth_params{"ans1"}) {
			my ($ans1, $ans2) = (lc($auth_params{"ans1"}), lc($auth_params{"ans2"}));
			$ans1 =~ s/[^a-z0-9]//g;
			$ans2 =~ s/[^a-z0-9]//g;
			#Just remembered the hash is stored in UC
			my ($ans1_hash, $ans2_hash) = (uc(sha1_hex($ans1)), uc(sha1_hex($ans2)));	
			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
			if ($con) {
				my $prep_stmt = $con->prepare("SELECT sec_qstn1,sec_qstn2,sec_qstn1_ans,sec_qstn2_ans FROM users WHERE u_id=? LIMIT 1");
				if ($prep_stmt) {
					my $rc = $prep_stmt->execute($u_id);
					if ($rc) {
						my @rslts = $prep_stmt->fetchrow_array();
						$prep_stmt->finish();
						if (@rslts) {
							$qstn1 = $rslts[0];
							$qstn2 = $rslts[1];
							my $db_ans1 = $rslts[2];
							my $db_ans2 = $rslts[3];	
							if (($db_ans1 eq $ans1_hash) and ($db_ans2 eq $ans2_hash)) {
								$success = 1;
								$sess_rec_code = gen_token(1);
								$session{"recover_code"} = $sess_rec_code;
							}
							else {
								$feedback = "One or more of the answers to the security questions is incorrect";
							}
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM users: ", $prep_stmt->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM users: ", $prep_stmt->errstr, $/;  
				}
				#$con->finish();
				$con->disconnect();
			}
			else {
				print STDERR "Cannot connect: $con->strerr$/";
			}	
		}
		else {
			$feedback = "You must provide answers to both security questions";
		}
	   }
	   #bogus auth token sent?
	   else {
		$feedback = "No authentication tokens received. Refresh your tokens by reloading this page.";
	   }
	}
	#no auth token sent?
	else {
		$feedback = "Invalid authentication tokens received. Do not alter any of the hidden values in the HTTP form.";
	}
		if ($success) {
			#write the reset password page
			$content =
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
<script>
function check_match() {
	var pass1 = document.getElementById("password1").value;
	var pass2 = document.getElementById("password2").value;
	if (pass1 !== pass2) {
		document.getElementById("match_feedback").innerHTML = '<tr><td colspan="2">The 2 passwords entered do not match';
		return false;
	}
	else {
		document.getElementById("reset_form").submit();
	}
}
</script>
</head>

<body>
$header
<p>Enter your new password
<FORM autocomplete="off" action="/cgi-bin/forgotpassword.cgi?stage=5&rec_code=$sess_rec_code" method="POST" id="reset_form">
<INPUT type="hidden" value="$conf_code" name="confirm_code">
<span style="color: red" id="match_feedback"></span>
<TABLE>
<tr>
<td><LABEL for="password1">New Password</LABEL>
<td><INPUT type="password" name="password1" value="" id="password1">
<tr>
<td><LABEL for="password2">Confirm New Password</LABEL>
<td><INPUT type="password" name="password2" value="" id="password2">
<tr>
<td><INPUT type="submit" name="reset" value="Reset" onclick="check_match()">
</TABLE>
</FORM>
};
		}
		else {
	$content =
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
</head>

<body>
$header
<span style="color: red">$feedback</span> 		
<p>To reset your password, answer the following security questions:<br><br>
<form autocomplete="off" action="/cgi-bin/forgotpassword.cgi?stage=4" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<table>
<tr><td><LABEL for="ans1" style="font-weight: bold">Security Question 1:&nbsp;&nbsp;</LABEL><LABEL for="ans1">$qstn1</LABEL>
<tr><td><LABEL for="ans1" style="font-weight: bold">Answer:</LABEL><INPUT type="text" name="ans1" value="">
<tr><td colspan="2">
<tr><td><LABEL for="ans2" style="font-weight: bold">Security Question 2:&nbsp;&nbsp;</LABEL><LABEL for="ans1">$qstn2</LABEL>
<tr><td><LABEL for="ans2" style="font-weight: bold">Answer:</LABEL><INPUT type="text" name="ans2" value="">
<tr><td><INPUT type="submit" name="send" value="Send">
</table>
</form>
</body>
</html>
};

		}
	}
}

#user inputs a username for which to recover 
#their password or the username is extracted
#from the 'username' field
if ($stage == 1) { 

	$content = 
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
</head>

<body>
$header
<span style="color: red">$feedback</span> 
<p>Type the username of the account that you would like to recover.
<form autocomplete="off" action="/cgi-bin/forgotpassword.cgi?stage=2" method="POST" > 
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<table>
<tr>
<td><LABEL for="u_name">Username:</LABEL>
<td><INPUT type="text" name="u_name" value="">
<tr>
<td colspan="2"><INPUT type="submit" name="recover" value="Recover">
</table>

</form>

</body>

</html>

};

}

#disambugation page
#multiple matches for given username
if ($stage == 3) {
	my $accounts_table = "";
	
	for my $user_id (keys %matched) {
		my ($qstn1, $qstn2) = @{$matched{$user_id}};
		$accounts_table .= qq{<tr><td><a href="/cgi-bin/forgotpassword.cgi?stage=2&u_id=$user_id">$user_id</a><td>1. $qstn1<br>2. $qstn2};
	}
	$content = 
qq{
<!DOCTYPE html>
<html lang='en'>

<head>
<title>Spanj :: Exam Management Information System :: Forgot Password</title>
</head>

<body>
$header
<p>The system has multiple users known as '$u_name'. Which of these accounts would you like to reset?
<table border="1">
<thead><th>User ID<th>Security Questions</thead>
<tbody>
$accounts_table
</table>

</body>

</html>

};
}


#found silly bug arising from altering the session
#auth tokens before they are read.
#put it here so it's altered just before output is sent
$session{"confirm_code"} = $conf_code;

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=iso-8859-1\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";
my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);
print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;


sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}
