#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

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

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) or accountant can rollback a payment voucher
		if ( $id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/search_voucher.cgi">Search Voucher</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to rollback a payment voucher.</span> Only the bursar and accountants are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Create Balance Sheet</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

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
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/search_payment_voucher.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Create Balance Sheet</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/search_payment_voucher.cgi">/login.html?cont=/cgi-bin/search_payment_voucher.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/search_payment_voucher.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
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
	#processing data sent 
	$post_mode++;
}

my @payment_vouchers;

if ($post_mode) {

	foreach ( keys %auth_params ) {
		if ( $_ =~ /payment_voucher_(\d+)/ ) {
			#don't want mischevious users doing their own cookery
			my $payment_voucher_no = $1;
			if ($auth_params{$_} eq $payment_voucher_no) {
				push @payment_vouchers, $payment_voucher_no;
			}
		}
	}
}

if ( scalar(@payment_vouchers) > 0 ) {

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my @voucher_voteheads = ();

	my $prep_stmt4 = $con->prepare("SELECT voucher_no,paid_out_to,amount,mode_payment,ref_id,description,votehead,time,hmac FROM payment_vouchers WHERE voucher_no=? LIMIT 1");

	if ($prep_stmt4) {

		for my $voucher (@payment_vouchers) {
	
			my $voucher_no = undef;

			my $rc = $prep_stmt4->execute($voucher);

			if ( $rc ) {
	
				while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
					
					$voucher_no = $rslts[0];
	
					my $paid_out_to = remove_padding($cipher->decrypt($rslts[1]));
					my $amount = remove_padding($cipher->decrypt($rslts[2]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[3]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[4]));
					my $descr = remove_padding($cipher->decrypt($rslts[5]));
					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {
						
						my $hmac = uc(hmac_sha1_hex($paid_out_to . $amount . $mode_payment . $ref_id . $descr . $votehead . $time, $key));

						if ( $hmac eq $rslts[8] ) {
							
							my @voteheads = split/,/, $votehead;
							foreach (@voteheads) {
								push @voucher_voteheads, $cipher->encrypt(add_padding($voucher_no . "-" . $_));
							}

						}
					}
				}

			}
			else {
				print STDERR "Couldn't prepare SELECT FROM payment_vouchers: ", $prep_stmt4->errstr, $/;			
			}
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM payment_vouchers: ", $prep_stmt4->errstr, $/;
	}

	my $prep_stmt7 = $con->prepare("DELETE FROM payment_vouchers WHERE voucher_no=? LIMIT 1");

	if ($prep_stmt7) {

		foreach (@payment_vouchers) {

			my $rc = $prep_stmt7->execute($_);
			unless ($rc) {
				print STDERR "Couldn't execute DELETE FROM payment_vouchers: ", $prep_stmt7->errstr, $/;	
			}

		}

	}

	else {
		print STDERR "Couldn't prepare DELETE FROM payment_vouchers: ", $prep_stmt7->errstr, $/;
	}

	my $prep_stmt8 = $con->prepare("DELETE FROM payments_book WHERE BINARY voucher_votehead=? LIMIT 1");

	if ($prep_stmt8) {

		foreach ( @voucher_voteheads ) {

			my $rc = $prep_stmt8->execute($_);

			unless ( $rc ) {
				print STDERR "Couldn't execute DELETE FROM payments_book: ", $prep_stmt8->errstr, $/;			
			}
		}
	}
	else {
		print STDERR "Couldn't prepare DELETE FROM payments_book: ", $prep_stmt8->errstr, $/;
	}

	$con->commit();

	#log action	
	my @today = localtime;	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       	if ($log_f) {

       		@today = localtime;	
		my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];	
		flock ($log_f, LOCK_EX) or print STDERR "Could not log rollback payment voucher for $id due to flock error: $!$/"; 
		seek ($log_f, 0, SEEK_END);
		foreach (@payment_vouchers) {
			print $log_f "$id ROLLBACK PAYMENT VOUCHER $_ $time\n";
		}

		flock ($log_f, LOCK_UN);
               	close $log_f;
       	}
	else {
		print STDERR "Could not log rollback payment voucher for $id: $!\n";
	}
	
	my $payment_voucher_list = '<ul>';
	foreach ( @payment_vouchers ) {
		$payment_voucher_list .= "<li>$_";
	}
	$payment_voucher_list .= '</ul>';

	$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Rollback Vouchers</title>
</head>
<body>
$header
<p>The following payment voucher(s) have been rolled back:
$payment_voucher_list
</body>
</html>
*;

}

else {
	$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Rollback Voucher</title>
</head>
<body>
$header
<p><span style="color: red">You did not specify any payment vouchers to rollback.</span>
</body>
</html>
* 
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

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
$con->disconnect() if (defined $con and $con);

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}
